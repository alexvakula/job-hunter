from fastapi.routing import APIRoute
from sqlmodel import select

from jobhunter.models import Job, StatusChange
from tests.integration.test_isolation import _routes


def _add(client, title="QA Lead", company="Acme"):
    resp = client.post("/jobs", data={"title": title, "company": company})
    assert resp.status_code == 303
    return int(resp.headers["location"].rsplit("/", 1)[1])


def test_board_shows_active_columns_and_hides_closed(two_users):
    alice, _ = two_users
    _add(alice)
    resp = alice.get("/board")
    assert resp.status_code == 200
    for label in ("New", "Interested", "Applied", "Screening", "Interview", "Offer", "Accepted"):
        assert f'data-status="{label.lower()}"' in resp.text
    assert 'data-status="rejected"' not in resp.text
    resp = alice.get("/board?closed=1")
    for status in ("rejected", "withdrawn", "ghosted"):
        assert f'data-status="{status}"' in resp.text


def test_kanban_drop_changes_status_via_htmx(two_users, session):
    alice, _ = two_users
    job_id = _add(alice)
    resp = alice.post(
        f"/jobs/{job_id}/status",
        data={"status": "interested"},
        headers={"HX-Request": "true", "HX-Target": f"card-{job_id}"},
    )
    assert resp.status_code == 200
    assert f'id="card-{job_id}"' in resp.text
    job = session.get(Job, job_id)
    session.refresh(job)
    assert job.status == "interested"


def test_job_page_status_with_effective_date(two_users, session):
    alice, _ = two_users
    job_id = _add(alice)
    for status in ("interested", "applied", "screening"):
        alice.post(f"/jobs/{job_id}/status", data={"status": status})
    resp = alice.post(
        f"/jobs/{job_id}/status", data={"status": "rejected", "effective_at": "2026-01-15T10:00"}
    )
    assert resp.status_code == 303
    history = session.exec(
        select(StatusChange).where(StatusChange.job_id == job_id).order_by(StatusChange.id)
    ).all()
    assert [h.to_status for h in history] == [
        "new",
        "interested",
        "applied",
        "screening",
        "rejected",
    ]
    page = alice.get(f"/jobs/{job_id}")
    assert "2026-01-15 10:00" in page.text


def test_htmx_status_from_job_page_returns_timeline(two_users):
    alice, _ = two_users
    job_id = _add(alice)
    resp = alice.post(
        f"/jobs/{job_id}/status",
        data={"status": "applied"},
        headers={"HX-Request": "true", "HX-Target": "status-section"},
    )
    assert resp.status_code == 200
    assert 'id="status-section"' in resp.text and "Applied" in resp.text


def test_invalid_status_is_422(two_users):
    alice, _ = two_users
    job_id = _add(alice)
    assert alice.post(f"/jobs/{job_id}/status", data={"status": "hired"}).status_code == 422
    future = "2099-01-01T00:00"
    assert (
        alice.post(
            f"/jobs/{job_id}/status", data={"status": "applied", "effective_at": future}
        ).status_code
        == 422
    )


def test_no_route_edits_or_deletes_history(app):
    for route in _routes(app):
        assert isinstance(route, APIRoute)
        assert "history" not in route.path and "status_change" not in route.path
        if "status" in route.path:
            assert route.methods == {"POST"}
            assert route.path == "/jobs/{job_id}/status"


def test_board_card_shows_days_in_status(two_users):
    alice, _ = two_users
    _add(alice, title="Board Job")
    resp = alice.get("/board")
    assert "Board Job" in resp.text and "today" in resp.text
