from sqlmodel import select

from jobhunter.models import Job, LocationRule, TargetProfile

CALGARY = {
    "rules-0-place": "Calgary, AB",
    "rules-0-onsite": "1",
    "rules-0-hybrid": "1",
    "rules-0-remote": "1",
    "rules-0-floor": "130000",
    "rules-0-currency": "CAD",
}
USA = {
    "rules-1-place": "USA",
    "rules-1-remote": "1",
    "rules-1-floor": "130,000",
    "rules-1-currency": "USD",
}


def _create(client, name="QA Lead", **extra):
    data = {
        "name": name,
        "synonyms": "Test Manager, QA Manager",
        "include_keywords": "selenium",
        "exclude_keywords": "junior, intern",
        "seniority": "Lead",
        **CALGARY,
        **extra,
    }
    return client.post("/settings/profiles/new", data=data)


def _profile(session, name):
    return session.exec(select(TargetProfile).where(TargetProfile.name == name)).one()


def test_settings_pages(two_users):
    alice, _ = two_users
    assert alice.get("/settings").status_code == 200
    assert alice.get("/settings/profiles").status_code == 200
    assert alice.get("/settings/profiles/new").status_code == 200


def test_create_profile_with_location_rules(two_users, session):
    alice, _ = two_users
    resp = _create(alice, **USA)
    assert resp.status_code == 303, resp.text
    p = _profile(session, "QA Lead")
    assert p.synonyms == ["Test Manager", "QA Manager"]
    assert p.exclude_keywords == ["junior", "intern"]
    assert p.seniority == "Lead"
    rules = session.exec(
        select(LocationRule).where(LocationRule.profile_id == p.id).order_by(LocationRule.id)
    ).all()
    assert [(r.place, sorted(r.work_modes), r.salary_floor, r.salary_currency) for r in rules] == [
        ("Calgary, AB", ["hybrid", "onsite", "remote"], 130000, "CAD"),
        ("USA", ["remote"], 130000, "USD"),
    ]
    assert "Calgary, AB" in alice.get("/settings/profiles").text


def test_validation(two_users, session):
    alice, _ = two_users
    assert _create(alice, name="").status_code == 422
    no_rules = {"name": "X", "rules-0-place": ""}
    assert alice.post("/settings/profiles/new", data=no_rules).status_code == 422
    no_modes = {"name": "X", "rules-0-place": "Calgary"}
    resp = alice.post("/settings/profiles/new", data=no_modes)
    assert resp.status_code == 422 and "work mode" in resp.text
    no_currency = {
        "name": "X",
        "rules-0-place": "Calgary",
        "rules-0-remote": "1",
        "rules-0-floor": "100000",
    }
    assert alice.post("/settings/profiles/new", data=no_currency).status_code == 422
    assert _create(alice).status_code == 303
    assert _create(alice).status_code == 422  # name unique per user
    assert session.exec(select(TargetProfile)).all().__len__() == 1


def test_same_name_allowed_for_different_users(two_users):
    alice, bob = two_users
    assert _create(alice).status_code == 303
    assert _create(bob).status_code == 303


def test_edit_replaces_rules(two_users, session):
    alice, _ = two_users
    _create(alice, **USA)
    p = _profile(session, "QA Lead")
    resp = alice.post(
        f"/settings/profiles/{p.id}",
        data={"name": "QA Lead", "rules-0-place": "Vancouver, BC", "rules-0-hybrid": "1"},
    )
    assert resp.status_code == 303
    rules = session.exec(select(LocationRule).where(LocationRule.profile_id == p.id)).all()
    assert [(r.place, r.work_modes) for r in rules] == [("Vancouver, BC", ["hybrid"])]


def test_one_default_and_pretagging(two_users, session):
    alice, _ = two_users
    _create(alice, name="A")
    _create(alice, name="B")
    a, b = _profile(session, "A"), _profile(session, "B")
    alice.post(f"/settings/profiles/{a.id}/default")
    alice.post(f"/settings/profiles/{b.id}/default")
    session.expire_all()
    assert not _profile(session, "A").is_default and _profile(session, "B").is_default
    page = alice.get("/jobs/new").text
    assert f'<option value="{b.id}" selected>B</option>' in page
    resp = alice.post("/jobs/prefill", data={"url": "", "text": "QA Lead\nCompany: X"})
    assert f'<option value="{b.id}" selected>B</option>' in resp.text


def test_tag_and_filter_by_profile(two_users, session):
    alice, _ = two_users
    _create(alice, name="A")
    a = _profile(session, "A")
    alice.post("/jobs", data={"title": "Tagged", "company": "C", "profile_id": str(a.id)})
    alice.post("/jobs", data={"title": "Untagged", "company": "D"})
    resp = alice.get(f"/jobs?profile={a.id}")
    assert "Tagged" in resp.text and "Untagged" not in resp.text


def test_cannot_tag_with_other_users_profile(two_users, session):
    alice, bob = two_users
    _create(bob, name="Bobs")
    p = _profile(session, "Bobs")
    resp = alice.post("/jobs", data={"title": "T", "company": "C", "profile_id": str(p.id)})
    assert resp.status_code == 422


def test_archive_hides_from_pickers_but_keeps_tags(two_users, session):
    alice, _ = two_users
    _create(alice, name="Old")
    p = _profile(session, "Old")
    alice.post(f"/settings/profiles/{p.id}/default")
    alice.post("/jobs", data={"title": "T", "company": "C", "profile_id": str(p.id)})
    alice.post(f"/settings/profiles/{p.id}/archive")
    session.expire_all()
    p = _profile(session, "Old")
    assert p.is_archived and not p.is_default
    assert ">Old</option>" not in alice.get("/jobs/new").text
    job = session.exec(select(Job)).one()
    assert job.profile_id == p.id
    assert "Old" in alice.get(f"/jobs/{job.id}").text


def test_delete_requires_confirm_and_untags_jobs(two_users, session):
    alice, _ = two_users
    _create(alice, name="Gone")
    p = _profile(session, "Gone")
    pid = p.id
    alice.post("/jobs", data={"title": "T", "company": "C", "profile_id": str(pid)})
    assert alice.post(f"/settings/profiles/{pid}/delete").status_code == 400
    assert (
        alice.post(f"/settings/profiles/{pid}/delete", data={"confirm": "yes"}).status_code == 303
    )
    session.expire_all()
    assert session.exec(select(TargetProfile)).all() == []
    assert session.exec(select(LocationRule)).all() == []
    assert session.exec(select(Job)).one().profile_id is None


def test_new_users_start_with_no_profiles(two_users):
    _, bob = two_users
    assert "No target positions yet" in bob.get("/settings/profiles").text


def test_no_source_picking(two_users):
    alice, _ = two_users
    page = alice.get("/settings/profiles/new").text
    assert 'name="source_ids"' not in page and "Every enabled job source is searched" in page
