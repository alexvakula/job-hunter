from pathlib import Path

import pytest
from sqlmodel import select

from jobhunter.db import today_local
from jobhunter.models import Contact, EmailMessage, Job, Source
from jobhunter.services.imap_client import decode_folder, encode_folder
from jobhunter.services.mail_link import (
    LinkResult,
    alert_source,
    apply_link,
    find_link,
    registrable,
)
from jobhunter.services.mail_store import store

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "emails"


@pytest.fixture
def ctx(session, make_user):
    user = make_user("alice")
    manual = session.exec(select(Source).where(Source.type == "manual")).one()

    def job(title, company, url=None, status="applied", contact=None):
        j = Job(
            user_id=user.id,
            title=title,
            company=company,
            company_title_key=company + title,
            source_id=manual.id,
            date_found=today_local(),
            status=status,
            url=url,
        )
        session.add(j)
        session.commit()
        if contact:
            session.add(Contact(job_id=j.id, name="c", email=contact))
            session.commit()
        return j

    def email(name="recruiter_reply.eml", **fields):
        e, _ = store(session, user.id, (FIX / name).read_bytes())
        for k, v in fields.items():
            setattr(e, k, v)
        session.add(e)
        session.commit()
        return e

    return {"user": user, "job": job, "email": email, "session": session}


def test_registrable():
    assert registrable("careers.acme.com") == "acme.com"
    assert registrable("jobs.canada.gc.ca") == "canada.gc.ca"
    assert registrable("localhost") is None


def test_contact_match(ctx):
    j = ctx["job"]("QA Lead", "Acme Robotics", contact="jane@acmerobotics.com")
    r = find_link(ctx["session"], ctx["user"].id, ctx["email"]())
    assert (r.job_id, r.method) == (j.id, "contact")


def test_two_jobs_same_contact_is_ambiguous(ctx):
    a = ctx["job"]("QA Lead", "Acme", contact="jane@acmerobotics.com")
    b = ctx["job"]("Test Lead", "Acme", contact="jane@acmerobotics.com")
    r = find_link(ctx["session"], ctx["user"].id, ctx["email"]())
    assert r.job_id is None and r.candidates == sorted([a.id, b.id])


def test_domain_match_via_posting_url(ctx):
    j = ctx["job"]("QA Lead", "Acme", url="https://careers.acmerobotics.com/jobs/1")
    ctx["job"]("Other", "Closed Co", url="https://acmerobotics.com/x", status="rejected")
    r = find_link(ctx["session"], ctx["user"].id, ctx["email"]())
    assert (r.job_id, r.method) == (j.id, "domain")


def test_free_mail_and_job_site_domains_never_match(ctx):
    ctx["job"]("QA", "Gmail Fans", url="https://gmail.com/careers")
    r = find_link(ctx["session"], ctx["user"].id, ctx["email"]("no_message_id.eml"))
    assert r.job_id is None
    ctx["job"]("QA", "X", url="https://jobs.lever.co/x/1")
    e = ctx["email"]("recruiter_reply.eml", from_addr="someone@lever.co")
    assert find_link(ctx["session"], ctx["user"].id, e).job_id is None


def test_reply_to_app_sent_email(ctx):
    j = ctx["job"]("QA Lead", "Northwind")
    sent = EmailMessage(
        user_id=ctx["user"].id,
        direction="out",
        kind="sent",
        dedupe_key="x",
        message_id="app-sent-1@example.org",
        job_id=j.id,
    )
    ctx["session"].add(sent)
    ctx["session"].commit()
    r = find_link(ctx["session"], ctx["user"].id, ctx["email"]("threaded_reply.eml"))
    assert (r.job_id, r.method) == (j.id, "reply")


def test_manual_link_never_overridden(ctx):
    e = ctx["email"](link_method="manual", job_id=None)
    apply_link(e, LinkResult(job_id=123, method="contact"))
    assert e.job_id is None and e.link_method == "manual"


def test_alert_source(ctx):
    s = ctx["session"]
    assert alert_source(s, "jobalerts-noreply@linkedin.com").name == "LinkedIn"
    assert alert_source(s, "donotreply@jobalert.indeed.com").name == "Indeed"
    assert alert_source(s, "jane@acmerobotics.com") is None


@pytest.mark.parametrize(
    "name", ["INBOX", "Job Alerts/LinkedIn", "Employers/Société Générale - QA", "A&B", "日本"]
)
def test_folder_name_utf7_roundtrip(name):
    encoded = encode_folder(name)
    assert encoded.isascii()
    assert decode_folder(encoded) == name


def test_folder_encoding_known_values():
    assert encode_folder("A&B") == "A&-B"
    assert encode_folder("Société") == "Soci&AOk-t&AOk-"
