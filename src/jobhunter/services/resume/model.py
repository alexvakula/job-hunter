"""Master resume content: structure, form parsing, validation and full text (FR-001, FR-003)."""

import re
import uuid

SECTION_FIELDS = {
    "experience": ("employer", "title", "location", "start", "end"),
    "education": ("institution", "credential", "field", "start", "end"),
    "certifications": ("name", "issuer", "date"),
}
CONTACT_FIELDS = ("name", "email", "phone", "location")
_KEY = re.compile(r"^(experience|education|certifications)-(\d+)-(\w+)$")


def empty() -> dict:
    return {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "links": [],
        "summary": "",
        "experience": [],
        "education": [],
        "certifications": [],
        "skills": [],
    }


def normalise(data: dict | None) -> dict:
    out = empty()
    for key, value in (data or {}).items():
        if key in out:
            out[key] = value
    for exp in out["experience"]:
        exp.setdefault("id", uuid.uuid4().hex[:8])
        exp.setdefault("bullets", [])
    return out


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
    data["skills"] = list(
        dict.fromkeys(
            s.strip() for s in re.split(r"[,\n;]", str(form.get("skills") or "")) if s.strip()
        )
    )
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
    parts = [d["name"], d["summary"], *d["skills"]]
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
