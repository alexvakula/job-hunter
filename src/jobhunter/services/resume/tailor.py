"""Rule-based tailoring and the honesty check (FR-006–FR-008, FR-010; constitution II)."""

from datetime import date

from jobhunter.services.resume import ats
from jobhunter.services.resume.model import full_text, normalise


def _relevance(text: str, keywords: list[str]) -> int:
    return sum(1 for k in keywords if ats.present(k, text))


def build_draft(master: dict, keywords: list[str]) -> dict:
    m = normalise(master)
    experience = []
    for exp in m["experience"]:
        bullets = [
            {"text": b, "source_index": i, "hidden": False}
            for i, b in enumerate(exp.get("bullets", []))
        ]
        bullets.sort(key=lambda b: -_relevance(b["text"], keywords))  # stable for ties
        experience.append({"id": exp["id"], "bullets": bullets})
    skills = [{"name": s, "hidden": False} for s in m["skills"]]
    skills.sort(key=lambda s: -_relevance(s["name"], keywords))
    return {"summary": m["summary"], "experience": experience, "skills": skills}


def apply_form(draft: dict, form) -> dict:
    """Editor changes: summary, bullet text/hidden/position, skill hidden/position."""
    out = {"summary": str(form.get("summary") or "").strip(), "experience": [], "skills": []}
    for exp in draft["experience"]:
        bullets = []
        for b in exp["bullets"]:
            key = f"b-{exp['id']}-{b['source_index']}"
            text = str(form.get(key + "-text") or b["text"]).strip() or b["text"]
            pos = _int(form.get(key + "-pos"), len(bullets) + 1)  # positions are 1-based
            bullets.append(
                (
                    {
                        "text": text,
                        "source_index": b["source_index"],
                        "hidden": form.get(key + "-hidden") == "1",
                    },
                    pos,
                )
            )
        bullets.sort(key=lambda x: x[1])
        out["experience"].append({"id": exp["id"], "bullets": [b for b, _ in bullets]})
    skills = []
    for i, s in enumerate(draft["skills"]):
        key = f"s-{i}"
        skills.append(
            (
                {"name": s["name"], "hidden": form.get(key + "-hidden") == "1"},
                _int(form.get(key + "-pos"), i + 1),
            )
        )
    skills.sort(key=lambda x: x[1])
    out["skills"] = [s for s, _ in skills]
    return out


def _int(value, default: int) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def snapshot(master: dict, draft: dict) -> dict:
    """What a generated resume contains: facts from the master, visible tailored items only."""
    m = normalise(master)
    by_id = {e["id"]: e for e in m["experience"]}
    experience = []
    for exp in m["experience"]:
        tailored = next((t for t in draft["experience"] if t["id"] == exp["id"]), None)
        bullets = (
            [b["text"] for b in tailored["bullets"] if not b["hidden"]]
            if tailored
            else exp.get("bullets", [])
        )
        e = by_id[exp["id"]]
        experience.append(
            {k: e.get(k, "") for k in ("employer", "title", "location", "start", "end")}
            | {"bullets": bullets}
        )
    return {
        "name": m["name"],
        "email": m["email"],
        "phone": m["phone"],
        "location": m["location"],
        "links": m["links"],
        "summary": draft.get("summary", ""),
        "experience": experience,
        "education": m["education"],
        "certifications": m["certifications"],
        "skills": [s["name"] for s in draft["skills"] if not s["hidden"]],
    }


def visible_text(snap: dict) -> str:
    parts = [snap["summary"], *snap["skills"]]
    for e in snap["experience"]:
        parts += [e["title"], e["employer"], *e["bullets"]]
    for e in snap["education"]:
        parts += [e.get("credential", ""), e.get("field", ""), e.get("institution", "")]
    for c in snap["certifications"]:
        parts += [c.get("name", ""), c.get("issuer", "")]
    return "\n".join(p for p in parts if p)


def honesty_flags(master: dict, editable_text: str, job_keywords: list[str]) -> list[str]:
    """Skills/tools/certs claimed in the user-editable text but absent from the master (FR-008)."""
    reference = full_text(master)
    claimed = set(ats.extract_keywords(editable_text))
    claimed |= {k for k in job_keywords if ats.present(k, editable_text)}
    return sorted(t for t in claimed if not ats.present(t, reference))


def editable_text(draft: dict, cover_letter: str) -> str:
    bullets = [b["text"] for e in draft["experience"] for b in e["bullets"] if not b["hidden"]]
    return "\n".join([draft.get("summary", ""), *bullets, cover_letter or ""])


COVER_LETTER_TEMPLATE = """{today}

Dear {contact},

I am writing to apply for the {title} position at {company}. {skills_sentence}

{summary}

{closing}

Sincerely,
{name}
"""


def default_cover_letter(master: dict, job, contact: str | None, keywords: list[str]) -> str:
    m = normalise(master)
    reference = full_text(m)
    top = [k for k in keywords if ats.present(k, reference)][:3]
    if top:
        listed = ", ".join(top[:-1]) + (" and " if len(top) > 1 else "") + top[-1]
        skills_sentence = f"My experience with {listed} matches what your team is looking for."
    else:
        skills_sentence = ""
    return COVER_LETTER_TEMPLATE.format(
        today=date.today().strftime("%B %-d, %Y"),
        contact=contact or "Hiring Manager",
        title=job.title,
        company=job.company,
        skills_sentence=skills_sentence,
        summary=m["summary"],
        name=m["name"] or "",
        closing=(
            f"I would welcome the opportunity to discuss how I can contribute to "
            f"{job.company}. Thank you for your time and consideration."
        ),
    ).replace("\n\n\n", "\n\n")
