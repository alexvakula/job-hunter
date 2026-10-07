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
