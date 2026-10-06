import json
from urllib.parse import parse_qs, urlsplit

import pytest

from jobhunter.models import LocationRule, TargetProfile
from jobhunter.services.search import boards, jobbank
from jobhunter.services.search.discovery import candidates
from jobhunter.services.search.postings import Posting, best_match, country_of, match
from tests.search_helpers import FIX


def _profile(exclude=("junior",), include=()):
    p = TargetProfile(
        id=1,
        user_id=1,
        name="QA Lead",
        synonyms=["Test Manager", "QA Manager", "Test Lead"],
        exclude_keywords=list(exclude),
        include_keywords=list(include),
    )
    rules = [
        LocationRule(
            profile_id=1,
            place="Calgary, AB",
            work_modes=["onsite", "hybrid", "remote"],
            salary_floor=130000,
            salary_currency="CAD",
        ),
        LocationRule(
            profile_id=1,
            place="Vancouver, BC",
            work_modes=["onsite", "hybrid", "remote"],
            salary_floor=130000,
            salary_currency="CAD",
        ),
        LocationRule(
            profile_id=1,
            place="USA",
            work_modes=["remote"],
            salary_floor=130000,
            salary_currency="USD",
        ),
    ]
    return p, rules


# --- matching and scoring ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "location", "remote", "expected"),
    [
        ("QA Lead", "Calgary (AB)", None, True),
        ("Software Quality Assurance (QA) Lead", "Vancouver, BC", None, True),
        ("Quality Assurance Lead", "United States", True, True),
        ("Manager, QA", "Remote (US)", True, True),
        ("Senior QA Lead", "Remote - United States", None, True),
        ("QA Lead", "Toronto (ON)", None, False),
        ("QA Lead", "Austin, TX", None, False),  # US on-site: USA rule is remote-only
        ("QA Lead", "Remote - Canada", True, True),  # remote in Canada, Calgary allows remote
        ("QA Lead", "Berlin", None, False),
        ("Backend Engineer", "Calgary, AB", None, False),
        ("QA Technician", "Calgary, AB", None, False),
        ("Junior QA Lead", "Calgary, AB", None, False),  # skip keyword
        ("Senior Manager, Quality Engineering", "Remote - US", True, True),  # QE = QA
        ("QE Lead", "Vancouver, BC", None, True),
        ("Compliance Lead, Testing", "Remote US", True, False),  # "testing" is not "test"
        ("Quality Engineer", "Calgary, AB", None, False),  # no lead/manager word
        ("QA Lead", "Toronto, Ontario; Calgary, Alberta", None, True),  # any of several places
        ("QA Lead", "Toronto, Ontario; Ottawa, Ontario", None, False),
        ("QA Lead", "Austin, TX; Remote - United States", None, True),
    ],
)
def test_match_rules(title, location, remote, expected):
    p, rules = _profile()
    got = match(Posting(title=title, url="u", location=location, remote=remote), p, rules)
    assert (got is not None) == expected


def test_include_keywords():
    p, rules = _profile(include=("selenium",))
    base = dict(title="QA Lead", url="u", location="Calgary, AB")
    assert match(Posting(**base, description="We use Cypress"), p, rules) is None
    assert match(Posting(**base, description="Selenium and Java"), p, rules) is not None


def test_scores_and_reasons():
    p, rules = _profile()
    exact_paid = match(
        Posting(
            title="QA Lead",
            url="u",
            location="Calgary, AB",
            salary_min=65,
            salary_max=65,
            currency="CAD",
            period="hour",
        ),
        p,
        rules,
    )
    partial_unknown = match(Posting(title="Manager, QA", url="u", location="Calgary, AB"), p, rules)
    below = match(
        Posting(
            title="QA Lead",
            url="u",
            location="Calgary, AB",
            salary_min=90000,
            salary_max=90000,
            currency="CAD",
            period="year",
        ),
        p,
        rules,
    )
    assert exact_paid.score == 100 and "salary ≥ CAD 130,000" in exact_paid.reasons
    assert partial_unknown.score == 75
    assert below.score == 80
    assert exact_paid.score > partial_unknown.score


def test_best_match_picks_highest_profile():
    p, rules = _profile()
    other = TargetProfile(
        id=2, user_id=1, name="Test Lead", synonyms=[], exclude_keywords=[], include_keywords=[]
    )
    m = best_match(
        Posting(title="Test Lead", url="u", location="Calgary"), [(p, rules), (other, rules)]
    )
    assert m.score == 90


@pytest.mark.parametrize(
    ("loc", "country"),
    [
        ("Calgary (AB)", "CA"),
        ("Toronto, Ontario, Canada", "CA"),
        ("Remote (US)", "US"),
        ("Austin, TX", "US"),
        ("United States", "US"),
        ("Berlin", None),
    ],
)
def test_country_of(loc, country):
    assert country_of(loc) == country


# --- Job Bank ------------------------------------------------------------------------------


def test_jobbank_queries_titles_by_canadian_places():
    p, rules = _profile()
    urls = jobbank.queries(p, rules)
    assert len(urls) == 4 * 2  # 4 titles × Calgary, Vancouver; USA skipped
    q = parse_qs(urlsplit(urls[0]).query)
    assert q["searchstring"] == ["QA Lead"] and q["locationstring"] == ["Calgary"]


def test_jobbank_feed_parsing():
    postings = jobbank.parse_feed((FIX / "jobbank_feed.xml").read_text())
    assert len(postings) == 9
    vancouver = next(p for p in postings if p.url.endswith("90000002"))
    assert vancouver.company == "Coastal Apps Inc." and vancouver.location == "Vancouver (BC)"
    assert (vancouver.salary_min, vancouver.salary_max, vancouver.currency, vancouver.period) == (
        140000,
        150000,
        "CAD",
        "year",
    )
    assert jobbank.parse_feed("<not xml") == []
    assert (
        jobbank.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>') == []
    )


# --- boards --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/acme", ("greenhouse", "acme", None, None)),
        ("https://job-boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme", None, None)),
        (
            "https://boards.greenhouse.io/embed/job_board?for=acme",
            ("greenhouse", "acme", None, None),
        ),
        ("https://jobs.lever.co/acme/abc-123", ("lever", "acme", None, None)),
        ("https://jobs.ashbyhq.com/acme", ("ashby", "acme", None, None)),
        (
            "https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/x",
            ("workday", "acme", "acme.wd3.myworkdayjobs.com", "Careers"),
        ),
        (
            "https://acme.wd3.myworkdayjobs.com/Careers",
            ("workday", "acme", "acme.wd3.myworkdayjobs.com", "Careers"),
        ),
        ("https://acme.pinpointhq.com/en/postings/aaaa-1", ("pinpoint", "acme", None, None)),
        ("https://ats.rippling.com/acme/jobs/r-1", ("rippling", "acme", None, None)),
        ("https://acme.applytojob.com/apply/AbC123/QA-Lead", ("jazzhr", "acme", None, None)),
        ("https://acme.applytojob.com/", ("jazzhr", "acme", None, None)),
        ("https://jobs.jobvite.com/acme/job/oAbC1", ("jobvite", "acme", None, None)),
        ("https://jobs.jobvite.com/acme/jobs", ("jobvite", "acme", None, None)),
    ],
)
def test_parse_board_link(url, expected):
    b = boards.parse_board_link(url)
    assert (b.type, b.board_id, b.host, b.site) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/1",
        "https://acme.com/careers",
        "https://jobs.lever.co/",
        "https://app.pinpointhq.com/login",
        "https://www.applytojob.com/",
        "https://ats.rippling.com/",
        "https://jobs.jobvite.com/",
        "https://jobs.dayforcehcm.com/en-US/acme/CANDIDATEPORTAL",
        "not a url",
    ],
)
def test_unsupported_links(url):
    assert boards.parse_board_link(url) is None


def test_board_parsers():
    gh = boards.parse_list(
        boards.Board("greenhouse", "acme"), (FIX / "greenhouse_jobs.json").read_text(), "Acme"
    )
    assert [p.title for p in gh][:2] == ["QA Lead", "Senior QA Lead"]
    assert gh[0].detail_url.endswith("/boards/acme/jobs/101") and gh[0].description is None
    lv = boards.parse_list(
        boards.Board("lever", "acme"), (FIX / "lever_postings.json").read_text(), "Acme"
    )
    assert lv[0].work_mode == "hybrid" and lv[0].url == "https://jobs.lever.co/acme/aaaa-1"
    ab = boards.parse_list(
        boards.Board("ashby", "acme"), (FIX / "ashby_board.json").read_text(), "Acme"
    )
    assert ab[1].remote is True and ab[0].work_mode == "onsite"
    wd_board = boards.Board("workday", "acme", "acme.wd3.myworkdayjobs.com", "Careers")
    wd = boards.parse_list(wd_board, (FIX / "workday_jobs.json").read_text(), "Acme")
    assert wd[0].url == "https://acme.wd3.myworkdayjobs.com/Careers/job/Calgary/QA-Lead_R1"
    assert boards.parse_list(wd_board, "garbage", "Acme") == []


def test_workday_multi_location_and_detail():
    board = boards.Board("workday", "acme", "acme.wd3.myworkdayjobs.com", "Careers")
    ps = boards.parse_list(board, (FIX / "workday_multi.json").read_text(), "Acme")
    assert ps[0].location is None
    assert ps[0].detail_url == (
        "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/job/Toronto/QA-Lead_R10"
    )
    detail = boards.workday_detail(json.loads((FIX / "workday_detail_r10.json").read_text()))
    assert detail["location"] == "Toronto, Ontario; Calgary, Alberta; Montreal, Quebec"
    assert detail["work_mode"] == "hybrid" and "test automation" in detail["description"]
    assert boards.workday_detail({}) == {"location": None, "work_mode": None, "description": None}


def test_more_board_parsers():
    pp = boards.parse_list(
        boards.Board("pinpoint", "acme"), (FIX / "pinpoint_postings.json").read_text(), "Acme"
    )
    assert pp[0].location == "Vancouver, British Columbia" and pp[0].work_mode == "hybrid"
    assert (pp[0].salary_min, pp[0].salary_max, pp[0].currency, pp[0].period) == (
        140000,
        150000,
        "CAD",
        "year",
    )
    assert "test automation" in pp[0].description and "Own the test strategy" in pp[0].description
    assert pp[1].salary_min is None and pp[1].remote is True  # salary hidden by the employer

    rp = boards.parse_list(
        boards.Board("rippling", "acme"), (FIX / "rippling_jobs.json").read_text(), "Acme"
    )
    assert [p.title for p in rp] == ["QA Lead", "Office Manager"]  # one posting per job
    assert rp[0].location == "Calgary, AB; Remote (Canada)" and rp[0].remote is True

    jz = boards.parse_list(
        boards.Board("jazzhr", "acme"), (FIX / "jazzhr_feed.xml").read_text(), "Acme"
    )
    assert [p.title for p in jz] == ["QA Lead"]  # closed jobs skipped
    assert jz[0].location == "Calgary, AB, Canada" and "test automation" in jz[0].description
    assert boards.parse_list(boards.Board("jazzhr", "acme"), "<not xml", "Acme") == []

    jv = boards.parse_list(
        boards.Board("jobvite", "acme"), (FIX / "jobvite_jobs.html").read_text(), "Acme"
    )
    assert [(p.title, p.location, p.url) for p in jv] == [
        (
            "QA Lead & Test Architect",
            "Vancouver, British Columbia",
            "https://jobs.jobvite.com/acme/job/oAbC1",
        ),
        ("Account Executive", "Remote, Canada", "https://jobs.jobvite.com/acme/job/oDeF2"),
    ]
    assert jv[1].remote is True
    assert boards.parse_list(boards.Board("jobvite", "acme"), "<html></html>", "Acme") == []


@pytest.mark.parametrize(
    ("kind", "url"),
    [
        ("pinpoint", "https://acme.pinpointhq.com/postings.json"),
        ("rippling", "https://api.rippling.com/platform/api/ats/v1/board/acme/jobs"),
        ("jazzhr", "https://app.jazz.co/feeds/export/jobs/acme"),
        ("jobvite", "https://jobs.jobvite.com/acme/jobs"),
    ],
)
def test_more_board_list_requests(kind, url):
    assert boards.list_request(boards.Board(kind, "acme")) == ("GET", url, None)


# --- discovery candidates ------------------------------------------------------------------


def test_discovery_candidates():
    assert candidates("Acme Robotics Inc.", "https://www.acmerobotics.com/about") == [
        "acmerobotics",
        "acme-robotics",
        "acme",
    ]
    assert candidates("Société Générale Technologies", None)[:2] == [
        "societegenerale",
        "societe-generale",
    ]
    assert candidates("AB", None) == ["ab"]
