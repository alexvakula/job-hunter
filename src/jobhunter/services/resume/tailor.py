"""Rule-based tailoring and the honesty check (FR-006–FR-008, FR-010; constitution II)."""

from datetime import date

from jobhunter.services.resume import ats
from jobhunter.services.resume.model import full_text, normalise


def _relevance(text: str, keywords: list[str]) -> int:
    return sum(1 for k in keywords if ats.present(k, text))


def posting_terms(master: dict, keywords: list[str]) -> list[str]:
    """Posting keywords missing from the master that a tailored resume adds for matching.

    Only known practices, tools and languages; never certifications or leadership claims.
    """
    reference = full_text(normalise(master))
    return [
        k
        for k in keywords
        if k in ats.TERMS and k not in ats.NEVER_ADDED and not ats.present(k, reference)
    ]


def top_up_from_posting(master: dict, skills: list[dict], keywords: list[str]) -> list[dict]:
    """Add the posting's missing skills a draft lacks, in the posting's own wording.

    Skills already listed (even hidden) stay as they are; the added ones are marked so the
    apply page can offer them with a box to untick.
    """
    names = {s["name"].casefold() for s in skills}
    added = [k for k in posting_terms(master, keywords) if k.casefold() not in names]
    return skills + [{"name": k, "hidden": False, "from_posting": True} for k in added]


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
    skills = top_up_from_posting(m, skills, keywords)
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
        if form.get(key + "-offer"):  # a posting skill offered with an "add" box
            hidden = form.get(key + "-add") != "1"
        else:
            hidden = form.get(key + "-hidden") == "1"
        group = form.get(key + "-group")  # "main" or "exposure": which box it was dragged to
        exposure = group == "exposure" if group else bool(s.get("exposure"))
        skills.append(
            (
                {"name": s["name"], "hidden": hidden}
                | ({"from_posting": True} if s.get("from_posting") else {})
                | ({"exposure": True} if exposure else {}),
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
    skills = [s["name"] for s in draft["skills"] if not s["hidden"] and not s.get("exposure")]
    exposure = [s["name"] for s in draft["skills"] if not s["hidden"] and s.get("exposure")]
    return {
        "name": m["name"],
        "headline": m["headline"] or (m["experience"][0]["title"] if m["experience"] else ""),
        "email": m["email"],
        "phone": m["phone"],
        "location": m["location"],
        "links": m["links"],
        "summary": draft.get("summary", ""),
        "experience": experience,
        "education": m["education"],
        "certifications": m["certifications"],
        "skills": skills + exposure,
        "skill_groups": _with_exposure(_skill_groups(m["skill_groups"], skills), exposure),
    }


def _skill_groups(groups: list[dict], skills: list[str]) -> list[dict]:
    """The master's skill groups holding only the shown skills, in tailored order."""
    if not groups:
        return [{"label": "", "skills": skills}] if skills else []
    out, placed = [], set()
    for g in groups:
        members = set(g["skills"])  # a skill may sit in several groups, as on paper
        shown = [s for s in skills if s in members]
        placed |= members
        if shown:
            out.append({"label": g["label"], "skills": shown})
    rest = [s for s in skills if s not in placed]
    if rest:
        out.append({"label": "Other", "skills": rest})
    return out


def _with_exposure(groups: list[dict], exposure: list[str]) -> list[dict]:
    """Skills moved to the "Exposure" box go last, joining the master's own group if any."""
    if not exposure:
        return groups
    for g in groups:
        if g["label"].casefold() == "exposure":
            g["skills"] = list(dict.fromkeys([*g["skills"], *exposure]))
            return groups
    return [*groups, {"label": "Exposure", "skills": exposure}]


def _unrelated(name: str, keywords: list[str]) -> bool:
    """A skill the posting never mentions that is not a known QA/dev term either."""
    if any(ats.present(k, name) for k in keywords) or ats.extract_keywords(name):
        return False
    return "test" not in name.casefold()


def skill_analysis(master: dict, skills: list[dict], keywords: list[str], visible: str) -> dict:
    """The posting's skills against the resume, and the resume's skills it could do without.

    rows: one per posting keyword, state "have" (in the tailored resume), "hidden" (in the
    master but not shown), "offer" (added from the posting; index/checked for its box)
    or "no" (not added: reason says why). remove: indexes of skills to suggest hiding.
    """
    reference = full_text(normalise(master))
    offered = {s["name"]: i for i, s in enumerate(skills) if s.get("from_posting")}
    rows = []
    for k in keywords:
        if k in offered:
            checked = not skills[offered[k]]["hidden"]
            rows.append({"term": k, "state": "offer", "index": offered[k], "checked": checked})
        elif ats.present(k, visible):
            rows.append({"term": k, "state": "have"})
        elif ats.present(k, reference):
            rows.append({"term": k, "state": "hidden"})
        else:
            reason = (
                "certification or leadership: add it to your master resume if true"
                if k in ats.NEVER_ADDED
                else "not a known skill: add it to your master resume if true"
            )
            rows.append({"term": k, "state": "no", "reason": reason})
    remove = [
        i
        for i, s in enumerate(skills)
        if s["name"] not in offered and not s["hidden"] and _unrelated(s["name"], keywords)
    ]
    return {"rows": rows, "remove": remove}


def visible_text(snap: dict) -> str:
    parts = [snap.get("headline", ""), snap["summary"], *snap["skills"]]
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
