"""Tables and enumerations (specs/001-job-tracker-mvp/data-model.md).

Enum-valued columns are stored as plain strings; services validate them against the enums.
Tables that carry `user_id` are owned by one user and must only be read through
`jobhunter.repo` so every query is scoped to that user.
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, text
from sqlmodel import Field, SQLModel

from jobhunter.db import utcnow


def _mail_host() -> str:
    from jobhunter.config import mail_host

    return mail_host()


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class Status(StrEnum):
    NEW = "new"
    INTERESTED = "interested"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"


ACTIVE_STATUSES: tuple[Status, ...] = (
    Status.NEW,
    Status.INTERESTED,
    Status.APPLIED,
    Status.SCREENING,
    Status.INTERVIEW,
    Status.OFFER,
    Status.ACCEPTED,
)
CLOSED_STATUSES: tuple[Status, ...] = (Status.REJECTED, Status.WITHDRAWN, Status.GHOSTED)


class WorkMode(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Currency(StrEnum):
    CAD = "CAD"
    USD = "USD"


class SalaryPeriod(StrEnum):
    YEAR = "year"
    HOUR = "hour"


class SourceType(StrEnum):
    MANUAL = "manual"
    JOB_BOARD = "job_board"
    ATS = "ats"
    ALERT_EMAIL = "alert_email"
    CAREERS_PAGE = "careers_page"
    ASSISTANT = "assistant"
    COMPANY_DIRECTORY = "company_directory"


def _fk(target: str, ondelete: str = "CASCADE", nullable: bool = False) -> Column:
    return Column(Integer, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# --- shared / account tables -------------------------------------------------------------


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_account"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=32)
    display_name: str = Field(max_length=80)
    role: str = Field(default=Role.USER.value)
    password_hash: str = Field(repr=False)
    must_change_password: bool = Field(default=False)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value


class UserSession(SQLModel, table=True):
    __tablename__ = "user_session"

    id: str = Field(primary_key=True, repr=False)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    csrf_token: str = Field(repr=False)
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


class LoginAttempt(SQLModel, table=True):
    __tablename__ = "login_attempt"
    __table_args__ = (Index("ix_login_attempt_lookup", "username", "ip", "at"),)

    id: int | None = Field(default=None, primary_key=True)
    username: str
    ip: str
    succeeded: bool = False
    at: datetime = Field(default_factory=utcnow)


class Source(SQLModel, table=True):
    __tablename__ = "source"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    type: str = Field(default=SourceType.JOB_BOARD.value)
    domains: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    fetch_allowed: bool = False
    enabled: bool = True
    is_system: bool = False
    alert_sender: bool = False  # sends job-alert emails (feature 002)


# --- owned tables ------------------------------------------------------------------------


class Job(SQLModel, table=True):
    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_user_status", "user_id", "status"),
        Index("ix_job_user_ct_key", "user_id", "company_title_key"),
        Index("ix_job_user_date_found", "user_id", "date_found"),
        Index(
            "ux_job_user_url_norm",
            "user_id",
            "url_norm",
            unique=True,
            sqlite_where=text("url_norm IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    title: str = Field(max_length=200)
    company: str = Field(max_length=200)
    location: str | None = None
    work_mode: str = Field(default=WorkMode.UNKNOWN.value)
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    url: str | None = None
    url_norm: str | None = None
    company_title_key: str
    source_id: int = Field(sa_column=_fk("source.id", ondelete="RESTRICT"))
    description: str = ""
    date_found: date
    status: str = Field(default=Status.NEW.value)
    profile_id: int | None = Field(
        default=None, sa_column=_fk("target_profile.id", ondelete="SET NULL", nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StatusChange(SQLModel, table=True):
    """Append-only history entry. There is deliberately no update/delete code path."""

    __tablename__ = "status_change"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(sa_column=_fk("job.id"))
    from_status: str | None = None
    to_status: str
    effective_at: datetime
    recorded_at: datetime = Field(default_factory=utcnow)


class Note(SQLModel, table=True):
    __tablename__ = "note"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(sa_column=_fk("job.id"))
    body: str = Field(max_length=20_000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    __tablename__ = "contact"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(sa_column=_fk("job.id"))
    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    profile_url: str | None = None
    notes: str | None = None


class FollowUp(SQLModel, table=True):
    __tablename__ = "follow_up"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(sa_column=_fk("job.id"))
    due_date: date
    description: str = Field(default="", max_length=200)
    done: bool = False
    done_at: datetime | None = None


class TargetProfile(SQLModel, table=True):
    __tablename__ = "target_profile"
    __table_args__ = (Index("ux_profile_user_name", "user_id", "name", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    name: str
    synonyms: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    include_keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    exclude_keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    seniority: str | None = None
    # No longer used: every source is searched for every position (kept for old rows).
    source_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_default: bool = False
    is_archived: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LocationRule(SQLModel, table=True):
    __tablename__ = "location_rule"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(sa_column=_fk("target_profile.id"))
    place: str
    work_modes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    salary_floor: int | None = None
    salary_currency: str | None = None


class SenderSettings(SQLModel, table=True):
    """One row per user. Never holds the mail password (read from env at use time)."""

    __tablename__ = "sender_settings"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
        )
    )
    from_address: str = ""
    display_name: str = ""
    reply_to: str = ""
    smtp_host: str = Field(default_factory=lambda: _mail_host())
    smtp_port: int = 587
    smtp_username: str = ""
    signature: str = ""
    bcc_self: bool = False


class ResumeFile(SQLModel, table=True):
    """An uploaded resume (US7). The bytes live on disk under `storage_name`, not in the DB."""

    __tablename__ = "resume_file"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    original_name: str = Field(max_length=200)
    storage_name: str = Field(unique=True)
    format: str
    size_bytes: int
    sha256: str
    is_current: bool = False
    uploaded_at: datetime = Field(default_factory=utcnow)


# --- feature 002: job mailbox --------------------------------------------------------------


class MailboxSettings(SQLModel, table=True):
    """One job-only mailbox per user. The password comes from SMTP_PASSWORD_<USERNAME>."""

    __tablename__ = "mailbox_settings"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
        )
    )
    address: str = Field(unique=True)
    imap_host: str = Field(default_factory=lambda: _mail_host())
    imap_port: int = 993
    checking_enabled: bool = True
    filing_enabled: bool = True
    last_check_at: datetime | None = None
    last_result: str | None = None
    last_error: str | None = None


class MailboxFolderState(SQLModel, table=True):
    __tablename__ = "mailbox_folder_state"
    __table_args__ = (Index("ux_folder_state", "user_id", "folder", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    folder: str
    uidvalidity: int = 0
    last_uid: int = 0


class EmailMessage(SQLModel, table=True):
    __tablename__ = "email_message"
    __table_args__ = (
        Index("ux_email_user_dedupe", "user_id", "dedupe_key", unique=True),
        Index("ix_email_user_saved", "user_id", "saved_at"),
        Index("ix_email_user_job", "user_id", "job_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    direction: str = "in"  # in | out
    kind: str = "other"  # alert | employer | other | sent
    dedupe_key: str
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    from_addr: str = ""
    from_name: str = ""
    reply_to: str | None = None
    to_addrs: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cc_addrs: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    subject: str = ""
    sent_at: datetime | None = None
    body_text: str = ""
    body_html: str | None = None
    raw_storage_name: str | None = None
    size_bytes: int = 0
    folder: str | None = None
    folder_uid: int | None = None
    moved_by_user: bool = False
    job_id: int | None = Field(
        default=None, sa_column=_fk("job.id", ondelete="SET NULL", nullable=True)
    )
    link_method: str = "none"  # reply | contact | domain | manual | none
    candidates: list[int] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    source_id: int | None = Field(
        default=None, sa_column=_fk("source.id", ondelete="SET NULL", nullable=True)
    )
    send_status: str | None = None  # pending | sent | failed (direction=out)
    send_error: str | None = None
    saved_at: datetime = Field(default_factory=utcnow)


class EmailAttachment(SQLModel, table=True):
    __tablename__ = "email_attachment"

    id: int | None = Field(default=None, primary_key=True)
    email_id: int = Field(sa_column=_fk("email_message.id"))
    filename: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    storage_name: str | None = None
    skipped: bool = False


class JobSuggestion(SQLModel, table=True):
    __tablename__ = "job_suggestion"
    __table_args__ = (Index("ux_suggestion_user_url", "user_id", "url_norm", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    email_id: int | None = Field(
        default=None, sa_column=_fk("email_message.id", ondelete="SET NULL", nullable=True)
    )
    source_id: int | None = Field(
        default=None, sa_column=_fk("source.id", ondelete="SET NULL", nullable=True)
    )
    title: str
    company: str | None = None
    location: str | None = None
    url: str
    url_norm: str
    state: str = "new"  # new | added | dismissed | tracked
    job_id: int | None = Field(
        default=None, sa_column=_fk("job.id", ondelete="SET NULL", nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow)
    # feature 003: automatic searches
    origin: str = "alert"  # alert | jobbank | watchlist
    watch_company_id: int | None = Field(
        default=None, sa_column=_fk("watch_company.id", ondelete="SET NULL", nullable=True)
    )
    profile_id: int | None = Field(
        default=None, sa_column=_fk("target_profile.id", ondelete="SET NULL", nullable=True)
    )
    description: str | None = None
    salary_text: str | None = None
    work_mode: str | None = None
    posted_at: datetime | None = None
    score: int | None = None
    score_reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # feature 005: Claude fit ranking
    fit_score: int | None = None
    fit_reason: str | None = None


# --- feature 003: automatic job search -----------------------------------------------------


class WatchCompany(SQLModel, table=True):
    """A company whose public job board is checked daily (per user)."""

    __tablename__ = "watch_company"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    name: str = Field(max_length=200)
    website: str | None = None
    # greenhouse | lever | ashby | workday | pinpoint | rippling | jazzhr | jobvite |
    # eightfold | phenom | successfactors | oracle | bamboohr | hibob | smartrecruiters | unknown
    board_type: str = "unknown"
    board_id: str | None = None
    board_host: str | None = None  # e.g. acme.wd3.myworkdayjobs.com, or a Phenom/SF career site
    board_site: str | None = None  # Workday site, Phenom path (ca/en), Eightfold domain
    status: str = "pending"  # ok | pending | not_found | error
    paused: bool = False
    imported: bool = False
    discovery_done: bool = False
    last_checked_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SearchRun(SQLModel, table=True):
    __tablename__ = "search_run"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    trigger: str = "user"  # daily | user
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: str = "running"  # running | ok | partial | failed
    summary: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


# --- feature 004: apply from the app ------------------------------------------------------


class MasterResume(SQLModel, table=True):
    """The user's structured resume: the single source of truth for facts (constitution II)."""

    __tablename__ = "master_resume"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
        )
    )
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    source_resume_id: int | None = Field(
        default=None, sa_column=_fk("resume_file.id", ondelete="SET NULL", nullable=True)
    )
    updated_at: datetime = Field(default_factory=utcnow)


class TailoredResume(SQLModel, table=True):
    __tablename__ = "tailored_resume"
    __table_args__ = (Index("ux_tailored_user_job", "user_id", "job_id", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    job_id: int = Field(sa_column=_fk("job.id"))
    summary: str = ""
    experience: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    skills: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cover_letter: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class DocumentVersion(SQLModel, table=True):
    """An immutable set of generated documents for one job (FR-011)."""

    __tablename__ = "document_version"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    job_id: int | None = Field(
        default=None, sa_column=_fk("job.id", ondelete="SET NULL", nullable=True)
    )
    number: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    content: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    ats_master: int | None = None
    ats_tailored: int | None = None
    resume_docx: str | None = None
    resume_pdf: str | None = None
    letter_docx: str | None = None
    letter_pdf: str | None = None


# --- feature 005: Claude integration -------------------------------------------------------


class ClaudeJob(SQLModel, table=True):
    """One queued Claude CLI run (constitution VI): processed one at a time by the worker."""

    __tablename__ = "claude_job"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    kind: str  # find_jobs | fit_rank | tailor | import | prep
    status: str = "queued"  # queued | running | done | failed
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    result: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    summary: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    model: str | None = None  # the Claude model the job ran with (feature 007)
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


# --- feature 006: reminders, export, interview prep ---------------------------------------


class NotificationSettings(SQLModel, table=True):
    """Per-user Telegram reminders. The bot token comes from TELEGRAM_BOT_TOKEN, never the DB."""

    __tablename__ = "notification_settings"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
        )
    )
    telegram_chat_id: str | None = None
    reminders_enabled: bool = True
    stale_days: int = 7
    last_sent_on: date | None = None
    last_error: str | None = None
    # New suggestions, employer emails and finished Claude tasks, sent as they come.
    updates_enabled: bool = False
    last_suggestion_id: int | None = None  # None: start from "now" on the next check
    last_email_id: int | None = None
    updates_checked_at: datetime | None = None


class EmailDraft(SQLModel, table=True):
    """An unsent email (Mail → Drafts): a reply to one email, or the application email for one
    job. One draft per email / per job, saved by the user or (replies) written by Claude."""

    __tablename__ = "email_draft"
    __table_args__ = (
        Index("ux_email_draft_user_email", "user_id", "email_id", unique=True),
        Index("ux_email_draft_user_job", "user_id", "job_id", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    kind: str = "reply"  # reply (email_id set) | application (job_id set)
    email_id: int | None = Field(default=None, sa_column=_fk("email_message.id", nullable=True))
    job_id: int | None = Field(default=None, sa_column=_fk("job.id", nullable=True))
    to_addrs: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    subject: str = ""
    body: str = ""
    attachments: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    intent: str | None = None  # replies: continue | withdraw
    by_claude: bool = False
    updated_at: datetime = Field(default_factory=utcnow)


class JobPrep(SQLModel, table=True):
    """Claude interview-prep and company notes for one job (admin only)."""

    __tablename__ = "job_prep"
    __table_args__ = (Index("ux_job_prep_user_job", "user_id", "job_id", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=_fk("user_account.id"))
    job_id: int = Field(sa_column=_fk("job.id"))
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class PostingDetail(SQLModel, table=True):
    """Public details of a board posting (places, work mode, description), looked up once
    and shared by all users: it holds no user data (feature 007)."""

    __tablename__ = "posting_detail"

    url_norm: str = Field(primary_key=True)
    location: str | None = None
    work_mode: str | None = None
    description: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
