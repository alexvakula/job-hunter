import pytest

from jobhunter.services.dedupe import company_title_key, normalize_company, normalize_url

SAME_URL = [
    ("https://boards.greenhouse.io/acme/jobs/123", "https://boards.greenhouse.io/acme/jobs/123/"),
    ("https://boards.greenhouse.io/acme/jobs/123", "HTTPS://Boards.Greenhouse.IO/acme/jobs/123"),
    (
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://boards.greenhouse.io/acme/jobs/123#app",
    ),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?utm_source=linkedin"),
    (
        "https://jobs.lever.co/acme/abc",
        "https://jobs.lever.co/acme/abc?utm_medium=x&utm_campaign=y",
    ),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?ref=feed"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?refId=abc123"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?trk=public_jobs"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?trackingId=Zz"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?src=email"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?gclid=1&fbclid=2"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?mc_cid=1&mc_eid=2"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?lipi=urn%3Ali"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abc?from=search"),
    (
        "https://jobbank.gc.ca/jobsearch/jobposting/123",
        "https://www.jobbank.gc.ca/jobsearch/jobposting/123",
    ),
    ("https://ca.indeed.com/viewjob?jk=abc&from=serp", "https://ca.indeed.com/viewjob?jk=abc"),
    ("https://ca.indeed.com/viewjob?a=1&jk=abc", "https://ca.indeed.com/viewjob?jk=abc&a=1"),
    ("https://www.linkedin.com/jobs/view/42/?trk=x&refId=y", "https://linkedin.com/jobs/view/42"),
    (
        "https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Calgary/QA_R1?source=x&utm_term=y",
        "https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Calgary/QA_R1?source=x",
    ),
    ("http://eluta.ca/job/1", "https://eluta.ca/job/1"),
    ("https://jobs.ashbyhq.com/acme/1?utm_source=a#top", "https://jobs.ashbyhq.com/acme/1"),
]

DIFFERENT_URL = [
    ("https://ca.indeed.com/viewjob?jk=abc", "https://ca.indeed.com/viewjob?jk=def"),
    (
        "https://www.linkedin.com/jobs/search/?currentJobId=1",
        "https://www.linkedin.com/jobs/search/?currentJobId=2",
    ),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/acme/abd"),
    ("https://jobs.lever.co/acme/abc", "https://jobs.lever.co/other/abc"),
    ("https://boards.greenhouse.io/acme/jobs/1", "https://job-boards.greenhouse.io/acme/jobs/1"),
]


@pytest.mark.parametrize(("a", "b"), SAME_URL)
def test_url_variants_normalise_equal(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_at_least_twenty_url_variants():
    assert len(SAME_URL) >= 20


@pytest.mark.parametrize(("a", "b"), DIFFERENT_URL)
def test_distinct_urls_stay_distinct(a, b):
    assert normalize_url(a) != normalize_url(b)


@pytest.mark.parametrize("bad", ["", "   ", "ftp://x/y", "javascript:alert(1)", "not a url"])
def test_invalid_urls_normalise_to_none(bad):
    assert normalize_url(bad) is None


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Acme Inc.", "ACME"),
        ("Acme, Incorporated", "acme"),
        ("Acme Ltd", "Acme Limited"),
        ("Acme LLC", "acme"),
        ("Acme Corp.", "Acme Corporation"),
        ("Acme Co.", "Acme Company"),
        ("Acme ULC", "Acme"),
        ("Acme LP", "Acme LLP"),
        ("Acme GmbH", "Acme PLC"),
        ("AT&T", "AT and T"),
        ("  Rogers   Communications ", "rogers communications"),
        ("Société Générale", "SOCIÉTÉ GÉNÉRALE"),
    ],
)
def test_company_variants_equal(a, b):
    assert normalize_company(a) == normalize_company(b)


def test_company_suffix_only_stripped_at_end():
    assert normalize_company("Co-operators Group") != normalize_company("Group")
    assert normalize_company("Company of Heroes") == "company of heroes"


def test_company_title_key_ignores_case_and_punctuation():
    assert company_title_key("Acme Inc.", "QA Lead!") == company_title_key("ACME", "qa  lead")
    assert company_title_key("Acme", "QA Lead") != company_title_key("Acme", "QA Manager")
