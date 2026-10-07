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
        (
            "https://acme.eightfold.ai/careers?domain=acme.example&query=qa",
            ("eightfold", "acme", None, "acme.example"),
        ),
        ("https://acme.eightfold.ai/careers/job/101", ("eightfold", "acme", None, "acme.com")),
        (
            "https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/501",
            ("oracle", "CX_1", "abcd.fa.us2.oraclecloud.com", None),
        ),
        (
            "https://careers.acme.example/hcmUI/CandidateExperience/en/sites/careers",
            ("oracle", "careers", "careers.acme.example", None),
        ),
        ("https://showpass.bamboohr.com/careers/143", ("bamboohr", "showpass", None, None)),
        ("https://helcim.careers.hibob.com/jobs/446c", ("hibob", "helcim", None, None)),
        (
            "https://careers.smartrecruiters.com/IFS1?search=copperleaf",
            ("smartrecruiters", "IFS1", None, "copperleaf"),
        ),
        (
            "https://jobs.smartrecruiters.com/IFS1/744000103561181-senior-product-manager",
            ("smartrecruiters", "IFS1", None, None),
        ),
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
        "https://www.bamboohr.com/careers",
        "https://www.hibob.com/careers",
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


def test_paged_site_parsers():
    ef_board = boards.Board("eightfold", "acme", site="acme.example")
    text = (FIX / "eightfold_search.json").read_text()
    ef = boards.parse_list(ef_board, text, "Acme")
    assert ef[0].url == "https://acme.eightfold.ai/careers/job/101"
    assert ef[0].location == "CALGARY, Alberta, Canada; EDMONTON, Alberta, Canada"
    assert ef[0].work_mode == "hybrid" and ef[0].posted_at.year == 2026
    assert boards.total_jobs(ef_board, text) == 2

    ph_board = boards.Board("phenom", "jobs.acme.example", "jobs.acme.example", "ca/en")
    text = (FIX / "phenom_search.html").read_text()
    ph = boards.parse_list(ph_board, text, "Acme")
    assert [p.url for p in ph] == [
        "https://jobs.acme.example/ca/en/job/R-100",
        "https://jobs.acme.example/ca/en/job/R-101",
    ]
    assert ph[0].location == "VANCOUVER, British Columbia, Canada; TORONTO, Ontario, Canada"
    assert boards.total_jobs(ph_board, text) == 2
    assert boards.parse_list(ph_board, "<html>no data</html>", "Acme") == []

    sf_board = boards.Board("successfactors", "jobs.acme.example", "jobs.acme.example")
    text = (FIX / "successfactors_search.html").read_text()
    sf = boards.parse_list(sf_board, text, "Acme")
    # "+2 more": the places come from the job's own page
    assert (sf[0].location, sf[0].detail_url, sf[0].detail_kind) == (
        None,
        "https://jobs.acme.example/job/Calgary-QA-Lead-AB/1001/",
        "successfactors",
    )
    assert [(p.title, p.location, p.url) for p in sf] == [
        ("QA Lead", None, "https://jobs.acme.example/job/Calgary-QA-Lead-AB/1001/"),
        (
            "Store Manager & Lead",
            "Toronto, ON, CA",
            "https://jobs.acme.example/Brand/job/Toronto-Store-Manager-ON/1002/",
        ),
    ]
    assert boards.total_jobs(sf_board, text) == 2
    detail = boards.successfactors_detail((FIX / "successfactors_job.html").read_text())
    assert detail["location"] == "Toronto, ON, CA; Calgary, AB, CA; Ottawa, ON, CA"
    assert "Lead test automation" in detail["description"]
    assert "Other field" not in detail["description"]


def test_oracle_parser():
    board = boards.Board("oracle", "CX_1", "abcd.fa.us2.oraclecloud.com")
    text = (FIX / "oracle_requisitions.json").read_text()
    ps = boards.parse_list(board, text, "Acme")
    assert ps[0].url == (
        "https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/501"
    )
    assert ps[0].location == "Toronto, Ontario, Canada; Vancouver, British Columbia, Canada"
    assert ps[0].work_mode == "hybrid" and ps[1].work_mode == "onsite"
    assert ps[0].description == "Lead testing of our security products."
    assert ps[0].posted_at.tzinfo is not None  # date-only values are taken as UTC
    assert boards.total_jobs(board, text) == 2
    assert boards.list_request(board, "QA Lead", 50)[1] == (
        "https://abcd.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
        "&finder=findReqs;siteNumber=CX_1,keyword=QA%20Lead,limit=50,offset=50"
    )
    assert boards.parse_list(board, "{}", "Acme") == []


def test_detect_career_sites():
    phenom = (FIX / "phenom_search.html").read_text()
    sf = (FIX / "successfactors_search.html").read_text()
    b = boards.detect_board("https://jobs.acme.example/ca/en/search-results", phenom)
    assert (b.type, b.host, b.site) == ("phenom", "jobs.acme.example", "ca/en")
    # a Phenom page from another host is not this site
    assert boards.detect_board("https://other.example/", phenom) is None
    b = boards.detect_board("https://jobs.acme.example/search/?q=", sf)
    assert (b.type, b.host, b.site) == ("successfactors", "jobs.acme.example", None)
    assert boards.detect_board("https://acme.example/careers", "<html>hi</html>") is None
    # newer ("unify") SuccessFactors sites list no jobs in the page: read through their feed
    unify = (
        '<html><body class="coreCSB search-page body unify body">'
        '<link href="https://rmkcdn.successfactors.com/x.css"></body></html>'
    )
    b = boards.detect_board("https://careers.deloitte.ca/search/", unify)
    assert (b.type, b.host, b.site) == ("successfactors", "careers.deloitte.ca", "feed")
    assert boards.list_request(b, "QA Lead", 50)[1] == "https://careers.deloitte.ca/sitemap.xml"
    assert boards.paged_limits(b) is None
    assert boards.paged_limits(boards.Board("successfactors", "h", host="h")) == (100, 50)


def test_successfactors_feed_parser():
    board = boards.Board("successfactors", "careers.deloitte.ca", "careers.deloitte.ca", "feed")
    ps = boards.parse_list(board, (FIX / "successfactors_feed.xml").read_text(), "Deloitte")
    calgary, multi, other = ps
    assert calgary.title == "Manager, Accounting & Reporting Assurance (ARA) - Calgary"
    assert calgary.location == "Calgary, AB" and calgary.work_mode == "hybrid"
    assert calgary.url.startswith("https://careers.deloitte.ca/job/")
    assert calgary.company == "Deloitte" and "Our Purpose" in calgary.description
    assert "Calgary, AB" in multi.location and "Toronto, ON" in multi.location
    assert multi.work_mode == "remote" and multi.remote
    assert other.location == "Toronto, ON, CA"  # no list of places: the posting's own, no postcode
    assert boards.parse_list(board, "not xml", "Deloitte") == []


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


def test_paged_list_requests_take_search_and_offset():
    req = boards.list_request
    assert req(boards.Board("eightfold", "acme", site="acme.example"), "QA Lead", 20)[1] == (
        "https://acme.eightfold.ai/api/pcsx/search?domain=acme.example&query=QA%20Lead"
        "&location=&start=20&num=10"
    )
    assert req(boards.Board("phenom", "h", "jobs.acme.example", "ca/en"), "QA Lead", 10)[1] == (
        "https://jobs.acme.example/ca/en/search-results?keywords=QA%20Lead&from=10"
    )
    sf = boards.Board("successfactors", "h", "jobs.acme.example")
    assert req(sf, "QA Lead", 25)[1] == "https://jobs.acme.example/search/?q=QA%20Lead&startrow=25"
    wd = boards.Board("workday", "acme", "acme.wd3.myworkdayjobs.com", "Careers")
    method, _url, body = req(wd, "QA Lead", 40)
    assert method == "POST" and (body["searchText"], body["offset"]) == ("QA Lead", 40)


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


def test_bamboohr_parser():
    board = boards.Board("bamboohr", "acme")
    ps = boards.parse_list(board, (FIX / "bamboohr_list.json").read_text(), "Acme")
    assert [p.title for p in ps] == [
        "QA Lead",
        "Full Stack Developer \u2013 Product Engineering",
        "Support Specialist",
    ]
    assert ps[0].url == "https://acme.bamboohr.com/careers/143"
    assert ps[0].location == "Calgary, Alberta" and ps[0].work_mode == "hybrid"
    assert ps[1].work_mode == "onsite" and not ps[1].remote
    assert ps[2].location == "Toronto, Ontario, Canada" and ps[2].remote
    assert ps[0].detail_url == "https://acme.bamboohr.com/careers/143/detail"
    assert ps[0].detail_kind == "bamboohr"
    d = boards.bamboohr_detail(json.loads((FIX / "bamboohr_detail.json").read_text()))
    assert d["location"] == "Calgary, Alberta, Canada"
    assert "Lead testing of our ticketing platform & mobile apps." in d["description"]
    assert boards.list_request(board)[1] == "https://acme.bamboohr.com/careers/list"
    assert boards.list_headers(board) is None
    assert boards.parse_list(board, "{}", "Acme") == []


def test_hibob_parser():
    board = boards.Board("hibob", "acme")
    ps = boards.parse_list(board, (FIX / "hibob_jobs.json").read_text(), "Acme")
    qa, analyst = ps
    assert qa.url == "https://acme.careers.hibob.com/jobs/446c36ce-d53f-4007-97c6-748b9a62e3c6"
    assert qa.location == "Calgary, Canada" and qa.work_mode == "hybrid"
    assert "Acme is searching for a QA Lead." in qa.description
    assert "Own our quality strategy & tooling" in qa.description
    assert "6+ years of test automation" in qa.description
    assert (qa.salary_min, qa.salary_max, qa.currency, qa.period) == (140000, 160000, "CAD", "year")
    assert qa.posted_at.year == 2026 and qa.posted_at.tzinfo is not None
    assert analyst.work_mode == "onsite" and analyst.salary_min is None and analyst.period is None
    assert boards.list_request(board)[1] == "https://acme.careers.hibob.com/api/job-ad"
    assert boards.list_headers(board) == {"companyIdentifier": "acme"}
    assert boards.parse_list(board, "[]", "Acme") == []


def test_smartrecruiters_parser():
    board = boards.Board("smartrecruiters", "acme", site="asset planning")
    page = (FIX / "smartrecruiters_page.html").read_text()
    ps = boards.parse_list(board, page, "Acme")
    assert len(ps) == 11  # the "Show more jobs" entry is not a job
    assert (ps[0].title, ps[0].location, ps[0].work_mode) == ("QA Lead", "Calgary, AB", "hybrid")
    assert ps[0].url == "https://jobs.smartrecruiters.com/acme/101-qa-lead"
    assert ps[1].location == "Toronto, ON" and ps[1].work_mode is None
    assert boards.smartrecruiters_pages(page) == (2, 0)
    assert boards.smartrecruiters_more(page) == ["Toronto%2C%20ON"]
    more = boards.parse_smartrecruiters_more(
        (FIX / "smartrecruiters_more.html").read_text(), "Acme", "Toronto, ON"
    )
    assert more[0].title == "Test Lead & Coach" and more[0].work_mode == "remote"
    assert boards.smartrecruiters_url(board, "groups", page=1) == (
        "https://careers.smartrecruiters.com/acme/api/groups?search=asset%20planning&page=1"
    )
    assert board.careers_url == "https://careers.smartrecruiters.com/acme?search=asset%20planning"
    d = boards.smartrecruiters_detail((FIX / "smartrecruiters_job.html").read_text())
    assert d["location"] == "Calgary, AB, Canada"
    assert "Lead testing of our asset planning software." in d["description"]
    assert "8+ years in QA" in d["description"] and "boilerplate" not in d["description"]
