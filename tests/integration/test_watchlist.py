import pytest
from sqlmodel import select

from jobhunter.models import Source, WatchCompany
from jobhunter.routes.watchlist import get_launcher
from jobhunter.services.fetch import FETCH_FAILED, get_fetcher
from tests.search_helpers import FIX, FakeFetcher


@pytest.fixture
def inline(app):
    fake = FakeFetcher()
    app.dependency_overrides[get_launcher] = lambda: lambda job: job()
    app.dependency_overrides[get_fetcher] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def _companies(session):
    session.expire_all()
    return session.exec(select(WatchCompany).order_by(WatchCompany.id)).all()


def test_add_by_link(two_users, session, inline):
    alice, _ = two_users
    assert (
        alice.post(
            "/watchlist", data={"careers_url": "https://jobs.lever.co/acme", "name": "Acme"}
        ).status_code
        == 303
    )
    assert (
        alice.post(
            "/watchlist", data={"careers_url": "https://acme.wd3.myworkdayjobs.com/en-US/Careers"}
        ).status_code
        == 303
    )
    bad = alice.post("/watchlist", data={"careers_url": "https://acme.com/careers"})
    assert bad.status_code == 422 and "Greenhouse, Lever" in bad.text
    dup = alice.post("/watchlist", data={"careers_url": "https://jobs.lever.co/acme/123"})
    assert dup.status_code == 422 and "already on your watchlist" in dup.text
    lever, wd = _companies(session)
    assert (lever.board_type, lever.board_id, lever.status) == ("lever", "acme", "ok")
    assert (wd.board_host, wd.board_site) == ("acme.wd3.myworkdayjobs.com", "Careers")
    assert "Acme" in alice.get("/watchlist").text


CSV = (
    "Company Name,Website,Sector\n"
    "Acme Robotics Inc.,https://acmerobotics.com,AI\n"
    "Beta Labs,beta.io,Health\n"
    "Gamma,,Energy\n"
    "acme robotics inc.,,dup by name\n"
    "Delta,https://acmerobotics.com,dup by website\n"
    ",https://noname.com,skipped\n"
)


def test_csv_import_and_discovery(two_users, session, inline):
    alice, _ = two_users
    inline.routes = {
        "https://boards-api.greenhouse.io/v1/boards/acmerobotics/jobs": ("fetched", '{"jobs": []}'),
        "https://api.lever.co/v0/postings/beta?": ("fetched", "[]"),
    }
    resp = alice.post("/watchlist/import", files={"file": ("abtec.csv", CSV.encode(), "text/csv")})
    assert resp.status_code == 200 and "Imported 3 companies (2 duplicates skipped)" in resp.text
    acme, beta, gamma = _companies(session)
    assert (acme.board_type, acme.board_id, acme.status) == ("greenhouse", "acmerobotics", "ok")
    assert (beta.board_type, beta.board_id) == ("lever", "beta")
    assert (gamma.board_type, gamma.status, gamma.discovery_done) == ("unknown", "not_found", True)
    hosts = {c[1].split("/")[2] for c in inline.calls}
    # only the job boards' public feeds are asked, never the companies' own websites
    board_hosts = {
        "boards-api.greenhouse.io",
        "api.lever.co",
        "api.ashbyhq.com",
        "api.rippling.com",
        "app.jazz.co",
    }
    assert all(h in board_hosts or h.endswith(".pinpointhq.com") for h in hosts)
    assert "gamma.pinpointhq.com" in hosts and "api.rippling.com" in hosts
    page = alice.get("/watchlist").text
    assert "3 of 3 checked, 2 job boards found" in page and "board not found" in page
    # a company without a board can be given its link by hand
    alice.post(
        f"/watchlist/{gamma.id}/link", data={"careers_url": "https://jobs.ashbyhq.com/gamma"}
    )
    session.refresh(gamma)
    assert (gamma.board_type, gamma.status) == ("ashby", "ok")


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://acme.pinpointhq.com/en/postings/aaaa-1", ("pinpoint", "acme")),
        ("https://ats.rippling.com/acme/jobs", ("rippling", "acme")),
        ("https://acme.applytojob.com/apply/AbC123/QA-Lead", ("jazzhr", "acme")),
        ("https://jobs.jobvite.com/acme/job/oAbC1", ("jobvite", "acme")),
    ],
)
def test_add_more_boards_by_link(two_users, session, inline, link, expected):
    alice, _ = two_users
    assert alice.post("/watchlist", data={"careers_url": link}).status_code == 303
    (c,) = _companies(session)
    assert (c.board_type, c.board_id, c.status) == (*expected, "ok")


def test_add_career_sites_by_link(two_users, session, inline):
    alice, _ = two_users
    inline.routes = {
        "https://jobs.acme.example/ca/en/job/R-100": "phenom_search.html",
        "https://careers.acme.example/careers": ("fetched", "<html>Welcome</html>"),
        "https://careers.acme.example/search/": "successfactors_search.html",
        "https://shop.example/": ("fetched", "<html>Just a shop</html>"),
        "https://www.careers.acme.example/ca/en": (
            "fetched",
            (FIX / "phenom_search.html")
            .read_text()
            .replace("https://jobs.acme.example/", "https://www.careers.acme.example/"),
        ),
    }
    for link in (
        "https://jobs.acme.example/ca/en/job/R-100",
        "https://careers.acme.example/careers",
        "https://acme.eightfold.ai/careers?domain=acme.example",
        "https://www.careers.acme.example/ca/en",
    ):
        assert alice.post("/watchlist", data={"careers_url": link}).status_code == 303
    bad = alice.post("/watchlist", data={"careers_url": "https://shop.example/"})
    assert bad.status_code == 422 and "SuccessFactors" in bad.text
    got = [(c.board_type, c.board_host, c.board_site) for c in _companies(session)]
    assert got == [
        ("phenom", "jobs.acme.example", "ca/en"),
        ("successfactors", "careers.acme.example", None),
        ("eightfold", None, "acme.example"),
        ("phenom", "www.careers.acme.example", "ca/en"),
    ]
    # the recognised sites may now be read by the daily searches
    domains = {
        s.name: s.domains
        for s in session.exec(select(Source).where(Source.name.in_(["Phenom", "SuccessFactors"])))
    }
    assert domains == {
        "Phenom": ["jobs.acme.example", "careers.acme.example"],  # without www., as compared
        "SuccessFactors": ["careers.acme.example"],
    }
    assert ("GET", "https://careers.acme.example/search/?q=", None) in inline.calls


def test_oracle_site_on_own_domain_is_allowed(two_users, session, inline):
    alice, _ = two_users
    for link in (
        "https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1",
        "https://careers.acme.example/hcmUI/CandidateExperience/en/sites/careers/job/7",
    ):
        assert alice.post("/watchlist", data={"careers_url": link}).status_code == 303
    got = [(c.board_type, c.board_id, c.board_host) for c in _companies(session)]
    assert got == [
        ("oracle", "CX_1", "abcd.fa.us2.oraclecloud.com"),
        ("oracle", "careers", "careers.acme.example"),
    ]
    oracle = session.exec(select(Source).where(Source.name == "Oracle Cloud")).one()
    session.refresh(oracle)
    # *.oraclecloud.com was already allowed; the employer's own domain is added
    assert oracle.domains == ["oraclecloud.com", "careers.acme.example"]
    assert inline.calls == []  # recognised from the link alone


def test_discovery_finds_new_boards(two_users, session, inline):
    alice, _ = two_users
    inline.routes = {
        "https://api.rippling.com/platform/api/ats/v1/board/acme/jobs": ("fetched", "[]"),
        "https://app.jazz.co/feeds/export/jobs/beta": (
            "fetched",
            '<?xml version="1.0"?><jobs><publisher>JazzHR</publisher></jobs>',
        ),
        "https://gamma.pinpointhq.com/postings.json": ("fetched", '{"data": []}'),
    }
    csv = "Company,Website\nAcme,acme.com\nBeta,beta.io\nGamma,gamma.dev\n"
    alice.post("/watchlist/import", files={"file": ("list.csv", csv.encode(), "text/csv")})
    found = [(c.name, c.board_type, c.board_id) for c in _companies(session)]
    assert found == [
        ("Acme", "rippling", "acme"),
        ("Beta", "jazzhr", "beta"),
        ("Gamma", "pinpoint", "gamma"),
    ]


def test_csv_semicolons_and_name_header(two_users, session, inline):
    alice, _ = two_users
    data = b"Name;Domain\nOne;one.com\nTwo;two.com\n"
    alice.post("/watchlist/import", files={"file": ("x.csv", data, "text/csv")})
    assert [c.name for c in _companies(session)] == ["One", "Two"]


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("x.csv", b"Sector,City\nAI,Calgary\n", "No company-name column"),
        ("x.xlsx", b"PK\x03\x04binary", "Save the list as CSV"),
        ("x.csv", b"", "empty"),
    ],
)
def test_bad_files(two_users, session, inline, name, data, message):
    alice, _ = two_users
    resp = alice.post("/watchlist/import", files={"file": (name, data, "text/csv")})
    assert resp.status_code == 422 and message in resp.text
    assert _companies(session) == []


def test_too_many_rows(two_users, session, inline, monkeypatch):
    import jobhunter.routes.watchlist as wl

    monkeypatch.setattr(wl, "MAX_ROWS", 2)
    alice, _ = two_users
    resp = alice.post(
        "/watchlist/import", files={"file": ("x.csv", b"Company\nA\nB\nC\n", "text/csv")}
    )
    assert resp.status_code == 422 and "Too many rows" in resp.text


def test_pause_and_remove(two_users, session, inline):
    alice, _ = two_users
    alice.post("/watchlist", data={"careers_url": "https://jobs.lever.co/acme"})
    c = _companies(session)[0]
    alice.post(f"/watchlist/{c.id}/pause")
    session.refresh(c)
    assert c.paused
    alice.post(f"/watchlist/{c.id}/delete")
    assert _companies(session) == []


def test_discovery_errors_mean_not_found(two_users, session, inline):
    alice, _ = two_users
    inline.routes = {"https://": (FETCH_FAILED, "timeout")}
    alice.post("/watchlist/import", files={"file": ("x.csv", b"Company\nZeta\n", "text/csv")})
    assert _companies(session)[0].status == "not_found"
