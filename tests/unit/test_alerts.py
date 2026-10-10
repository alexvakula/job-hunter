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


def _cts(url):
    import base64
    import gzip
    import json

    blob = base64.urlsafe_b64encode(gzip.compress(json.dumps({"u": url}).encode()))
    return f"https://cts.indeed.com/v3/{blob.decode().rstrip('=')}/sig"


def test_indeed_cts_tracker_is_unwrapped():
    from jobhunter.services.alerts import _indeed

    href = _cts("https://ca.indeed.com/rc/clk?jk=c0a0aebe7262abeb&from=email")
    assert _indeed(href) == "https://ca.indeed.com/viewjob?jk=c0a0aebe7262abeb"
    assert _indeed(_cts("https://match.indeed.com/invitations/pause?tk=1")) is None
    assert _indeed("https://cts.indeed.com/v3/not-base64/x") is None


def test_indeed_sponsored_jrtk_link():
    from jobhunter.services.alerts import _indeed

    href = (
        "https://ca.indeed.com/pagead/clk/dl?jrtk=5-cmh1-1-1k4bg0at7ke6p801-bcd0a0916728b58a&ad=x"
    )
    assert _indeed(href) == "https://ca.indeed.com/viewjob?jk=bcd0a0916728b58a"


def test_button_link_gives_way_to_title_link():
    job = "https://ca.indeed.com/viewjob?jk=a5ce1580d15e7f42"
    html = (
        f'<a href="{job}">View job</a><!--[if mso]>x<![endif]-->'
        '<a href="https://x.org">Bad match</a>'
        f'<p><a href="{job}">QA Lead</a></p><p>CoVet</p><p>Calgary, AB</p>'
    )
    [got] = parse_alert(html, "", "Indeed")
    assert (got.title, got.company, got.location) == ("QA Lead", "CoVet", "Calgary, AB")
