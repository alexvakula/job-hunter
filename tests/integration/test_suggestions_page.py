import re

from sqlmodel import select

from jobhunter.models import JobSuggestion, Source, UserAccount


def _add(session, uid, n, origin, url, source=None):
    sid = session.exec(select(Source.id).where(Source.name == source)).one() if source else None
    session.add(
        JobSuggestion(
            user_id=uid, title=f"Job {n}", url=url, url_norm=f"n{n}", origin=origin, source_id=sid
        )
    )
    session.commit()


def test_source_column(two_users, session):
    alice, _ = two_users
    uid = session.exec(select(UserAccount.id).where(UserAccount.username == "alice")).one()
    _add(session, uid, 1, "alert", "https://ca.indeed.com/viewjob?jk=1", "Indeed")
    _add(session, uid, 2, "watchlist", "https://job-boards.greenhouse.io/acme/jobs/2", "Greenhouse")
    _add(session, uid, 3, "claude", "https://jobs.lever.co/acme/3")  # no source recorded
    _add(session, uid, 4, "claude", "https://www.careers.acme.example/jobs/4")
    page = alice.get("/suggestions").text
    assert "<th>Source</th>" in page and "<th>Found by</th>" in page
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r">(Job \d) ↗</a>.*?<td>([^<]*)</td>\s*<td class=\"muted\">", page, re.S
        )
    }
    assert rows == {
        "Job 1": "Indeed",
        "Job 2": "Greenhouse",
        "Job 3": "Lever",
        "Job 4": "careers.acme.example",
    }


def test_dismissed_can_be_added_or_restored(two_users, session):
    alice, bob = two_users
    uid = session.exec(select(UserAccount.id).where(UserAccount.username == "alice")).one()
    _add(session, uid, 1, "watchlist", "https://job-boards.greenhouse.io/acme/jobs/1", "Greenhouse")
    _add(session, uid, 2, "watchlist", "https://job-boards.greenhouse.io/acme/jobs/2", "Greenhouse")
    one, two = session.exec(select(JobSuggestion).order_by(JobSuggestion.id)).all()
    for s in (one, two):
        alice.post(f"/suggestions/{s.id}/dismiss")
    page = alice.get("/suggestions?state=dismissed").text
    assert f"/suggestions/{one.id}/add" in page and f"/suggestions/{one.id}/restore" in page

    # Add a dismissed one: the add-job form opens; saving marks it added
    form = alice.post(f"/suggestions/{one.id}/add")
    assert form.status_code == 200 and 'value="Job 1"' in form.text
    resp = alice.post(
        "/jobs",
        data={
            "title": "Job 1",
            "company": "Acme",
            "url": one.url,
            "suggestion_id": str(one.id),
        },
    )
    assert resp.status_code == 303
    session.refresh(one)
    assert one.state == "added" and one.job_id is not None

    # Restore the other: back under New
    assert bob.post(f"/suggestions/{two.id}/restore").status_code == 404
    assert alice.post(f"/suggestions/{two.id}/restore").status_code == 303
    session.refresh(two)
    assert two.state == "new" and "Job 2" in alice.get("/suggestions").text
