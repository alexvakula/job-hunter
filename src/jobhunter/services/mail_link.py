"""Classifying emails and linking them to jobs (feature 002 research R4, FR-013–FR-015)."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlmodel import Session, select

from jobhunter.config import own_mail_domains
from jobhunter.models import CLOSED_STATUSES, Contact, EmailMessage, Job, Source

FREE_MAIL = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.ca",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "mail.com",
    "shaw.ca",
    "telus.net",
    "rogers.com",
    "sympatico.ca",
}
_TWO_LEVEL = {"co.uk", "com.au", "co.nz", "gc.ca", "ab.ca", "bc.ca", "on.ca", "qc.ca", "com.br"}


def registrable(host: str | None) -> str | None:
    host = (host or "").lower().strip(".")
    if not host or "." not in host:
        return None
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def email_domain(address: str | None) -> str | None:
    if not address or "@" not in address:
        return None
    return registrable(address.rsplit("@", 1)[1])


def _source_domains(session: Session) -> set[str]:
    domains: set[str] = set()
    for source in session.exec(select(Source)).all():
        for d in source.domains or []:
            reg = registrable(d)
            if reg:
                domains.add(reg)
    return domains


def alert_source(session: Session, from_addr: str) -> Source | None:
    """The alert-sending source whose domain matches the sender (FR-018), if any."""
    host = (from_addr.rsplit("@", 1)[1] if "@" in from_addr else "").lower()
    if not host:
        return None
    for source in session.exec(select(Source).where(Source.alert_sender.is_(True))).all():
        for domain in source.domains or []:
            reg = registrable(domain)
            if reg and (host == reg or host.endswith("." + reg)):
                return source
    return None


@dataclass
class LinkResult:
    job_id: int | None = None
    method: str = "none"
    candidates: list[int] = field(default_factory=list)


def _decide(job_ids: set[int], method: str) -> LinkResult | None:
    if len(job_ids) == 1:
        return LinkResult(job_id=next(iter(job_ids)), method=method)
    if len(job_ids) > 1:
        return LinkResult(method="none", candidates=sorted(job_ids))
    return None


def find_link(session: Session, user_id: int, email: EmailMessage) -> LinkResult:
    # (a) reply to an app-sent email that is linked to a job
    thread_ids = [i for i in [email.in_reply_to, *email.references] if i]
    if thread_ids:
        sent = session.exec(
            select(EmailMessage.job_id).where(
                EmailMessage.user_id == user_id,
                EmailMessage.direction == "out",
                EmailMessage.message_id.in_(thread_ids),
                EmailMessage.job_id.is_not(None),
            )
        ).all()
        decided = _decide(set(sent), "reply")
        if decided:
            return decided

    sender = (email.from_addr or "").lower()
    if not sender:
        return LinkResult()

    # (b) sender is a contact of exactly one job
    contact_jobs = session.exec(
        select(Contact.job_id)
        .join(Job, Job.id == Contact.job_id)
        .where(Job.user_id == user_id, Contact.email == sender)
    ).all()
    decided = _decide(set(contact_jobs), "contact")
    if decided:
        return decided

    # (c) sender's domain matches exactly one active job's company domain
    domain = email_domain(sender)
    excluded = FREE_MAIL | own_mail_domains() | _source_domains(session)
    if not domain or domain in excluded:
        return LinkResult()
    closed = [s.value for s in CLOSED_STATUSES]
    jobs = session.exec(select(Job).where(Job.user_id == user_id, Job.status.not_in(closed))).all()
    matches: set[int] = set()
    for job in jobs:
        domains = {registrable(urlsplit(job.url).hostname) if job.url else None}
        for contact in session.exec(select(Contact).where(Contact.job_id == job.id)).all():
            domains.add(email_domain(contact.email))
        if domain in domains:
            matches.add(job.id)
    return _decide(matches, "domain") or LinkResult()


def apply_link(email: EmailMessage, result: LinkResult) -> None:
    """Set the link unless the user chose one by hand (FR-015)."""
    if email.link_method == "manual":
        return
    email.job_id = result.job_id
    email.link_method = result.method if result.job_id else "none"
    email.candidates = result.candidates
    if email.direction == "in" and email.kind != "alert":
        email.kind = "employer" if email.job_id else "other"
