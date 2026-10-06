"""The four Claude job kinds: prompts, schemas and how results are applied (US2–US5)."""

import json
from dataclasses import dataclass

from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import (
    ClaudeJob,
    Job,
    JobSuggestion,
    MasterResume,
    ResumeFile,
    TailoredResume,
    UserAccount,
)
from jobhunter.services import resumes
from jobhunter.services.claude import cli
from jobhunter.services.dedupe import normalize_url
from jobhunter.services.resume import ats, importer, model, tailor
from jobhunter.services.search import runner
from jobhunter.services.search.postings import Posting, best_match, place_match

FIND_TIMEOUT, OTHER_TIMEOUT = 600, 180
DESCRIPTION_LIMIT, RESUME_LIMIT, POSTING_EXCERPT = 6000, 15000, 1500
RANK_BATCH = 20
RULES = (
    "Use only facts from the resume provided. Never invent or add skills, tools, employers, "
    "titles, dates, degrees or certifications."
)


@dataclass
class Outcome:
    summary: str
    result: dict
    cost_usd: float | None


def _master(session: Session, user: UserAccount) -> dict:
    m = session.get(MasterResume, user.id)
    if m is None or not model.normalise(m.data)["experience"]:
        raise cli.ClaudeError("Fill in your master resume first.")
    return model.normalise(m.data)


# --- find jobs -----------------------------------------------------------------------------

FIND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["jobs"],
    "properties": {
        "jobs": {
            "type": "array",
            "maxItems": 25,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "company", "location", "url"],
                "properties": {
                    "title": {"type": "string", "maxLength": 200},
                    "company": {"type": "string", "maxLength": 200},
                    "location": {"type": "string", "maxLength": 200},
                    "url": {"type": "string", "pattern": "^https?://", "maxLength": 1000},
                    "work_mode": {"enum": ["onsite", "hybrid", "remote", "unknown"]},
                    "salary_text": {"type": "string", "maxLength": 200},
                    "summary": {"type": "string", "maxLength": 1500},
                },
            },
        }
    },
}


def _find_prompt(profiles, master: dict) -> str:
    lines = ["Find current, open job postings on the web for this candidate.", ""]
    for p, rules in profiles:
        places = "; ".join(
            f"{r.place} ({'/'.join(r.work_modes)}"
            + (f", from {r.salary_currency} {r.salary_floor:,}/year" if r.salary_floor else "")
            + ")"
            for r in rules
        )
        lines.append(
            f"- Role: {p.name}; also: {', '.join(p.synonyms) or 'none'}; places: {places}"
            + (f"; avoid: {', '.join(p.exclude_keywords)}" if p.exclude_keywords else "")
        )
    lines += [
        "",
        f"Candidate summary: {master['summary'][:800]}",
        f"Key skills: {', '.join(master['skills'][:30])}",
        "",
        "Rules: return only real postings you found with web search that are open now, each "
        "with a direct link to the employer's careers page or its job board (Greenhouse, "
        "Lever, Ashby, Workday, Job Bank, etc.). Do not open LinkedIn, Indeed or Glassdoor "
        "pages. Do not guess links or make up postings. At most 25 results.",
    ]
    return "\n".join(lines)


def find_jobs(session: Session, user: UserAccount, job: ClaudeJob) -> Outcome:
    profiles = runner.active_profiles(session, user.id)
    if not profiles:
        raise cli.ClaudeError("Add a target position first.")
    out = cli.run(
        _find_prompt(profiles, _master(session, user)),
        FIND_SCHEMA,
        ["WebSearch", "WebFetch"],
        FIND_TIMEOUT,
        max_turns=25,
        model=cli.model_for("find_jobs"),
    )
    added, new_ids = 0, []
    for item in out.data["jobs"]:
        posting = Posting(
            title=item["title"],
            url=item["url"],
            company=item["company"],
            location=item["location"],
            description=item.get("summary"),
            salary_text=item.get("salary_text"),
            work_mode=None if item.get("work_mode") in (None, "unknown") else item["work_mode"],
        )
        m = best_match(posting, profiles)
        if m is None and not any(place_match(posting, r) for _p, rules in profiles for r in rules):
            continue
        url_norm = normalize_url(posting.url)
        if (
            url_norm is None
            or session.exec(
                select(JobSuggestion.id).where(
                    JobSuggestion.user_id == user.id, JobSuggestion.url_norm == url_norm
                )
            ).first()
        ):
            continue
        tracked = session.exec(
            select(Job.id).where(Job.user_id == user.id, Job.url_norm == url_norm)
        ).first()
        s = JobSuggestion(
            user_id=user.id,
            origin="claude",
            title=posting.title[:200],
            company=posting.company,
            location=posting.location,
            url=posting.url,
            url_norm=url_norm,
            description=posting.description,
            salary_text=posting.salary_text,
            work_mode=posting.work_mode,
            score=m.score if m else None,
            score_reasons=m.reasons if m else [],
            profile_id=m.profile_id if m else None,
            state="tracked" if tracked else "new",
            job_id=tracked,
        )
        session.add(s)
        session.commit()
        if s.state == "new":  # already-tracked ones are recorded but not counted or ranked
            added += 1
            new_ids.append(s.id)
    from jobhunter.services.claude.queue import enqueue

    if new_ids:
        enqueue(session, user, "fit_rank", {"suggestion_ids": new_ids})
    return Outcome(
        f"{len(out.data['jobs'])} postings found, {added} new suggestions.",
        {"suggestion_ids": new_ids},
        out.cost_usd,
    )


# --- fit ranking ---------------------------------------------------------------------------

RANK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rankings"],
    "properties": {
        "rankings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "score", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string", "maxLength": 200},
                },
            },
        }
    },
}


def fit_rank(session: Session, user: UserAccount, job: ClaudeJob) -> Outcome:
    master = _master(session, user)
    ids = job.payload.get("suggestion_ids")
    stmt = select(JobSuggestion).where(
        JobSuggestion.user_id == user.id, JobSuggestion.state == "new"
    )
    stmt = (
        stmt.where(JobSuggestion.id.in_(ids))
        if ids
        else stmt.where(JobSuggestion.fit_score.is_(None))
    )
    batch = session.exec(stmt.order_by(JobSuggestion.id).limit(RANK_BATCH)).all()
    if not batch:
        return Outcome("Nothing to rank.", {"ranked": 0}, None)
    postings = [
        {
            "id": s.id,
            "title": s.title,
            "company": s.company,
            "location": s.location,
            "description": (s.description or "")[:POSTING_EXCERPT],
        }
        for s in batch
    ]
    prompt = (
        "Score how well each job posting fits this candidate, 0 (no fit) to 100 (excellent), "
        "with a one-line reason (max 200 characters). Judge only from the resume and the "
        "posting.\n\nRESUME:\n"
        + model.full_text(master)[:RESUME_LIMIT]
        + "\n\nPOSTINGS (JSON):\n"
        + json.dumps(postings, ensure_ascii=False)
    )
    out = cli.run(
        prompt, RANK_SCHEMA, [], OTHER_TIMEOUT, max_turns=3, model=cli.model_for("fit_rank")
    )
    by_id = {s.id: s for s in batch}
    ranked = 0
    for r in out.data["rankings"]:
        s = by_id.get(r["id"])
        if s is None:
            continue  # ignore ids that were not sent
        s.fit_score, s.fit_reason = r["score"], r["reason"][:200]
        session.add(s)
        ranked += 1
    session.commit()
    return Outcome(f"{ranked} suggestions ranked.", {"ranked": ranked}, out.cost_usd)


# --- tailoring -----------------------------------------------------------------------------

TAILOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "bullets", "cover_letter"],
    "properties": {
        "summary": {"type": "string", "maxLength": 1500},
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "text"],
                "properties": {
                    "ref": {"type": "string", "maxLength": 40},
                    "text": {"type": "string", "maxLength": 600},
                },
            },
        },
        "cover_letter": {"type": "string", "maxLength": 6000},
    },
}


def tailor_job(session: Session, user: UserAccount, job: ClaudeJob) -> Outcome:
    master = _master(session, user)
    target = session.get(Job, job.payload.get("job_id"))
    if target is None or target.user_id != user.id:
        raise cli.ClaudeError("The job no longer exists.")
    keywords = ats.extract_keywords(target.description or "")
    resume_json = {
        "summary": master["summary"],
        "experience": [
            {
                "employer": e["employer"],
                "title": e["title"],
                "bullets": [
                    {"ref": f"{e['id']}:{i}", "text": b} for i, b in enumerate(e["bullets"])
                ],
            }
            for e in master["experience"]
        ],
        "skills": master["skills"],
        "education": master["education"],
        "certifications": master["certifications"],
    }
    prompt = (
        f"Tailor this resume for the job below. {RULES} Rephrase the summary and existing "
        "bullets (refer to each bullet by its ref) to mirror the posting's wording where it "
        "is true for the candidate; you may omit bullets you do not change. Then write a "
        "concise cover letter (under 350 words) to the hiring manager, using only true "
        f"facts. Sign it with the candidate's name: {master['name']}.\n\n"
        f"JOB: {target.title} at {target.company}\n{(target.description or '')[:DESCRIPTION_LIMIT]}"
        f"\n\nKEYWORDS: {', '.join(keywords)}\n\nRESUME (JSON):\n"
        + json.dumps(resume_json, ensure_ascii=False)[:RESUME_LIMIT]
    )
    out = cli.run(
        prompt, TAILOR_SCHEMA, [], OTHER_TIMEOUT, max_turns=3, model=cli.model_for("tailor")
    )

    t = session.exec(
        select(TailoredResume).where(
            TailoredResume.user_id == user.id, TailoredResume.job_id == target.id
        )
    ).first()
    if t is None:
        d = tailor.build_draft(master, keywords)
        t = TailoredResume(
            user_id=user.id,
            job_id=target.id,
            summary=d["summary"],
            experience=d["experience"],
            skills=d["skills"],
        )
    texts = {b["ref"]: b["text"].strip() for b in out.data["bullets"] if b["text"].strip()}
    changed = 0
    experience = []
    for exp in t.experience:
        bullets = []
        for b in exp["bullets"]:
            ref = f"{exp['id']}:{b['source_index']}"
            if ref in texts:
                b = {**b, "text": texts[ref]}
                changed += 1
            bullets.append(b)
        experience.append({**exp, "bullets": bullets})
    t.experience = experience  # unknown refs are ignored: no new bullets (FR-008)
    t.summary = out.data["summary"].strip() or t.summary
    t.cover_letter = out.data["cover_letter"].strip() or t.cover_letter
    t.updated_at = utcnow()
    session.add(t)
    session.commit()
    flags = tailor.honesty_flags(
        master,
        tailor.editable_text(
            {"summary": t.summary, "experience": t.experience, "skills": t.skills}, t.cover_letter
        ),
        keywords,
    )
    note = f" Check flagged terms: {', '.join(flags)}." if flags else ""
    return Outcome(
        f"Summary, {changed} bullets and the cover letter rewritten.{note}",
        {"job_id": target.id, "flags": flags},
        out.cost_usd,
    )


# --- import --------------------------------------------------------------------------------

_ROW = {"type": "string", "maxLength": 300}
IMPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "email",
        "phone",
        "location",
        "links",
        "summary",
        "experience",
        "education",
        "certifications",
        "skills",
    ],
    "properties": {
        "name": _ROW,
        "email": _ROW,
        "phone": _ROW,
        "location": _ROW,
        "links": {"type": "array", "items": _ROW},
        "summary": {"type": "string", "maxLength": 3000},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["employer", "title", "location", "start", "end", "bullets"],
                "properties": {
                    "employer": _ROW,
                    "title": _ROW,
                    "location": _ROW,
                    "start": _ROW,
                    "end": _ROW,
                    "bullets": {"type": "array", "items": {"type": "string", "maxLength": 1000}},
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["institution", "credential", "field", "start", "end"],
                "properties": {
                    k: _ROW for k in ("institution", "credential", "field", "start", "end")
                },
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "issuer", "date"],
                "properties": {k: _ROW for k in ("name", "issuer", "date")},
            },
        },
        "skills": {"type": "array", "items": {"type": "string", "maxLength": 100}},
    },
}


def import_resume(session: Session, user: UserAccount, job: ClaudeJob) -> Outcome:
    f = session.get(ResumeFile, job.payload.get("resume_file_id"))
    if f is None or f.user_id != user.id:
        raise cli.ClaudeError("Upload your resume first.")
    data = resumes.path_for(f).read_bytes()
    lines = importer.lines_from_docx(data) if f.format == "docx" else importer.lines_from_pdf(data)
    text = "\n".join(("• " if line.bullet else "") + line.text for line in lines)
    if not text.strip():
        raise cli.ClaudeError("No text could be read from the uploaded resume.")
    prompt = (
        "Convert this resume into the JSON structure, copying facts exactly as written (do "
        "not improve, summarise or invent anything; use empty strings or lists for missing "
        f"parts).\n\nRESUME TEXT:\n{text[:RESUME_LIMIT]}"
    )
    out = cli.run(
        prompt, IMPORT_SCHEMA, [], OTHER_TIMEOUT, max_turns=3, model=cli.model_for("import")
    )
    master = model.normalise(out.data)
    return Outcome(
        f"{len(master['experience'])} jobs, {len(master['skills'])} skills read. "
        "Review them in the editor before saving.",
        master,
        out.cost_usd,
    )


HANDLERS = {
    "find_jobs": find_jobs,
    "fit_rank": fit_rank,
    "tailor": tailor_job,
    "import": import_resume,
}
