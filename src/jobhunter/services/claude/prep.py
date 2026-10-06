"""Claude interview prep and company notes for one job (feature 006 US3, FR-005)."""

import json

from sqlmodel import Session, select

from jobhunter.db import utcnow
from jobhunter.models import ClaudeJob, Job, JobPrep, UserAccount
from jobhunter.services.claude import cli
from jobhunter.services.claude.tasks import (
    DESCRIPTION_LIMIT,
    FIND_TIMEOUT,
    RESUME_LIMIT,
    RULES,
    Outcome,
    _master,
)

PREP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["company_overview", "questions", "questions_to_ask"],
    "properties": {
        "company_overview": {"type": "string", "maxLength": 2500},
        "questions": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question", "why", "answer_outline", "resume_refs"],
                "properties": {
                    "question": {"type": "string", "maxLength": 400},
                    "why": {"type": "string", "maxLength": 400},
                    "answer_outline": {"type": "string", "maxLength": 1200},
                    "resume_refs": {"type": "array", "items": {"type": "string", "maxLength": 40}},
                },
            },
        },
        "questions_to_ask": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 300},
        },
    },
}


def prep_job(session: Session, user: UserAccount, job: ClaudeJob) -> Outcome:
    master = _master(session, user)
    target = session.get(Job, job.payload.get("job_id"))
    if target is None or target.user_id != user.id:
        raise cli.ClaudeError("The job no longer exists.")
    refs = {f"{e['id']}:{i}": b for e in master["experience"] for i, b in enumerate(e["bullets"])}
    resume_json = {
        "summary": master["summary"],
        "skills": master["skills"],
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
    }
    prompt = (
        f"Prepare the candidate for an interview for {target.title} at {target.company}. "
        "1) Write a short, factual company overview (what they do, size, recent news) using web "
        "search; do not open LinkedIn, Indeed or Glassdoor pages; say when unsure. 2) List likely "
        "interview questions for this posting; for each, why it is likely and an answer outline "
        "built ONLY from the candidate's resume, citing the bullet refs used. "
        f"{RULES} 3) Suggest questions the candidate can ask.\n\nPOSTING:\n"
        f"{(target.description or '')[:DESCRIPTION_LIMIT]}\n\nRESUME (JSON):\n"
        + json.dumps(resume_json, ensure_ascii=False)[:RESUME_LIMIT]
    )
    out = cli.run(prompt, PREP_SCHEMA, ["WebSearch", "WebFetch"], FIND_TIMEOUT, max_turns=15)
    data = out.data
    for q in data["questions"]:
        q["resume_refs"] = [r for r in q["resume_refs"] if r in refs]  # drop unknown refs
        q["resume_quotes"] = [refs[r] for r in q["resume_refs"]]
    prep = session.exec(
        select(JobPrep).where(JobPrep.user_id == user.id, JobPrep.job_id == target.id)
    ).first()
    prep = prep or JobPrep(user_id=user.id, job_id=target.id)
    prep.data, prep.updated_at = data, utcnow()
    session.add(prep)
    session.commit()
    return Outcome(
        f"{len(data['questions'])} likely questions and a company overview ready.",
        {"job_id": target.id},
        out.cost_usd,
    )
