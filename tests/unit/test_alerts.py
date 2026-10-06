import json
from pathlib import Path

import pytest

from jobhunter.services.alerts import parse_alert
from jobhunter.services.mail_store import parse_email

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "emails"
EXPECTED = json.loads((FIX / "expected.json").read_text())
SOURCE_OF = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "glassdoor": "Glassdoor",
    "jobbank": "Job Bank",
}


def _parse(name):
    p = parse_email((FIX / name).read_bytes())
    return parse_alert(p.body_html, p.body_text, SOURCE_OF[name.split("_")[0]])


@pytest.mark.parametrize("name", sorted(k for k in EXPECTED if k != "linkedin_not_alert.eml"))
def test_alert_fixtures(name):
    got = [vars(j) for j in _parse(name)]
    assert got == EXPECTED[name]


def test_extraction_rate_and_no_invention():
    total = found = 0
    for name, jobs in EXPECTED.items():
        if name == "linkedin_not_alert.eml":
            continue
        got = {j.url for j in _parse(name)}
        total += len(jobs)
        found += sum(1 for j in jobs if j["url"] in got)
        assert got <= {j["url"] for j in jobs}  # nothing invented
    assert found / total >= 0.95


def test_non_alert_email_from_job_site_gives_nothing():
    assert _parse("linkedin_not_alert.eml") == []


def test_unknown_source_gives_nothing():
    p = parse_email((FIX / "linkedin_alert_1.eml").read_bytes())
    assert parse_alert(p.body_html, p.body_text, "Workopolis") == []
