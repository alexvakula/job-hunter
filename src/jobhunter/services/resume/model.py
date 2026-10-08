"""Master resume content: structure, form parsing, validation and full text (FR-001, FR-003)."""

import re
import uuid

SECTION_FIELDS = {
    "experience": ("employer", "title", "location", "start", "end"),
    "education": ("institution", "credential", "field", "start", "end"),
    "certifications": ("name", "issuer", "date"),
}
CONTACT_FIELDS = ("name", "headline", "email", "phone", "location")
_KEY = re.compile(r"^(experience|education|certifications)-(\d+)-(\w+)$")
_GROUP = re.compile(r"^([^:,;]{1,40}):\s*(.*)$")  # "Tools: Jira, Postman"


def empty() -> dict:
    return {
        "name": "",
        "headline": "",
        "email": "",
        "phone": "",
        "location": "",
        "links": [],
        "summary": "",
        "experience": [],
        "education": [],
        "certifications": [],
        "skills": [],
        "skill_groups": [],
    }


def normalise(data: dict | None) -> dict:
    out = empty()
    for key, value in (data or {}).items():
        if key in out:
            out[key] = value
    for exp in out["experience"]:
        exp.setdefault("id", uuid.uuid4().hex[:8])
        exp.setdefault("bullets", [])
    grouped = [s for g in out["skill_groups"] for s in g.get("skills", [])]
    out["skills"] = list(dict.fromkeys([*out["skills"], *grouped]))
    return out


def parse_skills(text: str) -> tuple[list[str], list[dict]]:
    """Skills box → (skills, groups). A line "Label: a, b" is a group; other lines are plain."""
    skills: list[str] = []
    groups: list[dict] = []
    for line in (text or "").splitlines():
        m = _GROUP.match(line.strip())
        items = [s.strip() for s in re.split(r"[,;]", m.group(2) if m else line) if s.strip()]
        if m and items:
            groups.append({"label": m.group(1).strip(), "skills": items})
        skills += items
    return list(dict.fromkeys(skills)), groups


def skills_text(data: dict) -> str:
    """The skills box: one "Label: a, b" line per group, then the ungrouped skills."""
    lines = [f"{g['label']}: {', '.join(g['skills'])}" for g in data.get("skill_groups", [])]
    grouped = {s for g in data.get("skill_groups", []) for s in g["skills"]}
    rest = [s for s in data.get("skills", []) if s not in grouped]
    return "\n".join(lines + ([", ".join(rest)] if rest else []))


def _lines(text: str) -> list[str]:
    return [
        line.strip().lstrip("•-*·").strip()
        for line in (text or "").splitlines()
        if line.strip().lstrip("•-*·").strip()
    ]


def from_form(form) -> tuple[dict, dict[str, str]]:
    """Editor fields → data, errors. Rows are `section-<i>-<field>`; blank rows are dropped."""
    data = empty()
    for f in CONTACT_FIELDS:
        data[f] = str(form.get(f) or "").strip()
    data["links"] = _lines(str(form.get("links") or ""))
    data["summary"] = str(form.get("summary") or "").strip()
    data["skills"], data["skill_groups"] = parse_skills(str(form.get("skills") or ""))
    rows: dict[tuple[str, int], dict] = {}
    for key in form.keys():
        m = _KEY.match(key)
        if m:
            rows.setdefault((m.group(1), int(m.group(2))), {})[m.group(3)] = str(
                form.get(key) or ""
            )
    errors: dict[str, str] = {}
    for (section, index), row in sorted(rows.items()):
        values = {f: row.get(f, "").strip() for f in SECTION_FIELDS[section]}
        if section == "experience":
            bullets = _lines(row.get("bullets", ""))
            if not any(values.values()) and not bullets:
                continue
            if not values["employer"] or not values["title"]:
                errors[f"experience-{index}"] = "Each job needs an employer and a title."
            values["bullets"] = bullets
            values["id"] = row.get("id", "").strip() or uuid.uuid4().hex[:8]
        elif not any(values.values()):
            continue
        elif section == "education" and not values["institution"]:
            errors[f"education-{index}"] = "Each school needs an institution."
        elif section == "certifications" and not values["name"]:
            errors[f"certifications-{index}"] = "Each certification needs a name."
        data[section].append(values)
    if data["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", data["email"]):
        errors["email"] = "Enter a valid email address."
    return data, errors


def full_text(data: dict) -> str:
    """Everything in the master resume as plain text (the honesty reference, FR-008)."""
    d = normalise(data)
    parts = [d["name"], d["headline"], d["summary"], *d["skills"]]
    for e in d["experience"]:
        parts += [
            e.get("title", ""),
            e.get("employer", ""),
            e.get("location", ""),
            *e.get("bullets", []),
        ]
    for e in d["education"]:
        parts += [e.get("credential", ""), e.get("field", ""), e.get("institution", "")]
    for c in d["certifications"]:
        parts += [c.get("name", ""), c.get("issuer", "")]
    return "\n".join(p for p in parts if p)
