"""Local ATS keyword extraction and coverage scoring (FR-004, FR-005)."""

import re
from dataclasses import dataclass, field

# canonical term -> spelling variants (lower case). Kept focused on software/QA work.
# Testing practices: postings name the same work many ways, so variants matter most here.
PRACTICES: dict[str, tuple[str, ...]] = {
    "test automation": (
        "test automation",
        "automated testing",
        "automation testing",
        "automated tests",
        "test automation framework",
    ),
    "manual testing": ("manual testing",),
    "regression testing": (
        "regression testing",
        "regression tests",
        "regression suite",
        "regression suites",
    ),
    "performance testing": (
        "performance testing",
        "load testing",
        "stress testing",
        "performance tests",
        "scalability testing",
    ),
    "security testing": ("security testing", "penetration testing"),
    "API testing": ("api testing", "api tests", "api automation", "api test automation"),
    "integration testing": ("integration testing",),
    "unit testing": ("unit testing", "unit tests"),
    "end-to-end testing": ("end-to-end testing", "e2e testing", "end to end testing"),
    "exploratory testing": ("exploratory testing",),
    "mobile testing": ("mobile testing", "mobile app testing"),
    "accessibility testing": ("accessibility testing", "wcag"),
    "UAT": ("uat", "user acceptance testing"),
    "test strategy": ("test strategy", "test strategies"),
    "test plans": ("test plan", "test plans", "test planning"),
    "test cases": ("test case", "test cases"),
    "test management": ("test management",),
    "defect management": (
        "defect management",
        "defect tracking",
        "bug tracking",
        "defect triage",
        "bug triage",
        "defect lifecycle",
    ),
    "risk-based testing": ("risk-based testing", "risk based testing"),
    "TDD": ("tdd", "test-driven development", "test driven development"),
    "BDD": ("bdd", "behavior-driven development", "behaviour-driven development"),
    "shift-left": ("shift-left", "shift left"),
    "functional testing": ("functional testing", "functional tests"),
    "non-functional testing": ("non-functional testing", "nonfunctional testing"),
    "smoke testing": ("smoke testing", "smoke tests"),
    "sanity testing": ("sanity testing", "sanity checks"),
    "system testing": ("system testing", "system integration testing", "system tests"),
    "acceptance testing": ("acceptance testing", "acceptance criteria", "acceptance tests"),
    "black-box testing": ("black-box testing", "black box testing"),
    "white-box testing": ("white-box testing", "white box testing"),
    "usability testing": ("usability testing",),
    "cross-browser testing": (
        "cross-browser testing",
        "cross browser testing",
        "browser compatibility",
    ),
    "compatibility testing": ("compatibility testing", "device compatibility"),
    "data-driven testing": ("data-driven testing", "data driven testing"),
    "contract testing": ("contract testing", "consumer-driven contract"),
    "visual testing": ("visual testing", "visual regression"),
    "static testing": ("static testing", "reviews and inspections"),
    "release testing": ("release testing", "release validation", "release readiness"),
    "embedded testing": (
        "embedded testing",
        "embedded software testing",
        "hardware-in-the-loop",
        "hil testing",
    ),
    "test design": ("test design", "test case design", "test scenarios"),
    "test data management": ("test data management", "test data"),
    "test environments": ("test environment", "test environments"),
    "test reporting": ("test reporting", "test reports", "test metrics", "quality metrics"),
    "test coverage": ("test coverage", "code coverage", "coverage analysis"),
    "test documentation": ("test documentation", "test artifacts", "test artefacts"),
    "test estimation": ("test estimation", "test effort estimation"),
    "requirements analysis": ("requirements analysis", "requirement analysis"),
    "requirements traceability": ("requirements traceability", "traceability matrix", "rtm"),
    "verification and validation": ("verification and validation", "v&v"),
    "root cause analysis": ("root cause analysis", "root-cause analysis"),
    "quality assurance": ("quality assurance",),
    "quality engineering": ("quality engineering",),
    "QA processes": ("qa process", "qa processes", "quality processes", "testing processes"),
    "service virtualization": ("service virtualization", "mock services", "mock api", "mocking"),
    "Page Object Model": ("page object model", "page object pattern", "page objects"),
}

TERMS: dict[str, tuple[str, ...]] = {
    **PRACTICES,
    # tools
    "Selenium": ("selenium", "webdriver"),
    "Cypress": ("cypress",),
    "Playwright": ("playwright",),
    "Appium": ("appium",),
    "TestNG": ("testng",),
    "JUnit": ("junit",),
    "pytest": ("pytest",),
    "NUnit": ("nunit",),
    "xUnit": ("xunit",),
    "Jest": ("jest",),
    "Mocha": ("mocha",),
    "WireMock": ("wiremock",),
    "WinAppDriver": ("winappdriver",),
    "Locust": ("locust",),
    "Cucumber": ("cucumber", "gherkin"),
    "Postman": ("postman",),
    "SoapUI": ("soapui",),
    "JMeter": ("jmeter",),
    "Gatling": ("gatling",),
    "k6": ("k6",),
    "LoadRunner": ("loadrunner",),
    "TestRail": ("testrail",),
    "Zephyr": ("zephyr",),
    "Xray": ("xray",),
    "Jira": ("jira",),
    "Confluence": ("confluence",),
    "TestComplete": ("testcomplete",),
    "Katalon": ("katalon",),
    "Robot Framework": ("robot framework",),
    "BrowserStack": ("browserstack",),
    "Sauce Labs": ("sauce labs", "saucelabs"),
    "SonarQube": ("sonarqube",),
    "Git": ("git",),
    "GitHub": ("github",),
    "GitLab": ("gitlab",),
    "Jenkins": ("jenkins",),
    "GitHub Actions": ("github actions",),
    "Azure DevOps": ("azure devops",),
    "CircleCI": ("circleci",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"),
    "Terraform": ("terraform",),
    "Linux": ("linux",),
    # languages and tech
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript",),
    "TypeScript": ("typescript",),
    "C#": ("c#",),
    "C++": ("c++",),
    "Go": ("golang",),
    "Ruby": ("ruby",),
    "Kotlin": ("kotlin",),
    "Swift": ("swift",),
    "SQL": ("sql",),
    "Bash": ("bash", "shell scripting"),
    "PowerShell": ("powershell",),
    "REST APIs": ("rest api", "rest apis", "restful"),
    "GraphQL": ("graphql",),
    "microservices": ("microservices", "micro-services"),
    # ways of working
    "Agile": ("agile",),
    "Scrum": ("scrum",),
    "Kanban": ("kanban",),
    "SAFe": ("safe agile", "scaled agile"),
    "CI/CD": (
        "ci/cd",
        "cicd",
        "continuous integration",
        "continuous delivery",
        "continuous deployment",
    ),
    "DevOps": ("devops",),
    "SDLC": ("sdlc",),
    "STLC": ("stlc",),
    # leadership
    "team leadership": (
        "team leadership",
        "led a team",
        "lead a team",
        "leading a team",
        "people management",
        "managed a team",
    ),
    "mentoring": ("mentoring", "mentored", "mentor", "mentorship", "coaching"),
    "stakeholder management": ("stakeholder management", "stakeholders"),
    # certifications
    "ISTQB": ("istqb",),
    "CSQA": ("csqa",),
    "CSTE": ("cste",),
    "PMP": ("pmp",),
    "Certified ScrumMaster": ("certified scrummaster", "certified scrum master", "csm"),
}
# Never added to a tailored resume from the posting: credentials and leadership claims are
# facts, not something to read up on before an interview.
NEVER_ADDED = {
    "ISTQB",
    "CSQA",
    "CSTE",
    "PMP",
    "Certified ScrumMaster",
    "team leadership",
    "mentoring",
    "stakeholder management",
}
_IGNORE_ACRONYMS = {
    "US",
    "USA",
    "CA",
    "UK",
    "EU",
    "AND",
    "THE",
    "OR",
    "HR",
    "EOE",
    "EEO",
    "CEO",
    "CTO",
    "CFO",
    "VP",
    "NYC",
    "SF",
    "AI",
    "ML",
    "IT",
    "OK",
    "PST",
    "EST",
    "MST",
    "LLC",
    "INC",
    "LTD",
    "PTO",
    "FAQ",
    "AB",
    "BC",
    "ON",
    "QC",
    "TX",
    "NY",
    "WA",
    "QA",
}
_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")


def _pattern(variant: str) -> re.Pattern:
    return re.compile(r"(?<![\w#+])" + re.escape(variant) + r"(?![\w#+])", re.IGNORECASE)


_COMPILED = {term: [_pattern(v) for v in variants] for term, variants in TERMS.items()}


def present(term: str, text: str) -> bool:
    patterns = _COMPILED.get(term) or [_pattern(term)]
    return any(p.search(text or "") for p in patterns)


def extract_keywords(text: str) -> list[str]:
    """Dictionary terms in order of first appearance, then repeated all-caps acronyms."""
    text = text or ""
    found: list[tuple[int, str]] = []
    for term, patterns in _COMPILED.items():
        positions = [m.start() for p in patterns for m in [p.search(text)] if m]
        if positions:
            found.append((min(positions), term))
    terms = [t for _, t in sorted(found)]
    known = {v.upper() for variants in TERMS.values() for v in variants} | {
        t.upper() for t in terms
    }
    known |= {part for k in known for part in re.split(r"[/&\s-]+", k) if part}  # CI/CD: CI, CD
    counts: dict[str, int] = {}
    for a in _ACRONYM.findall(text):
        if a not in _IGNORE_ACRONYMS and a not in known:
            counts[a] = counts.get(a, 0) + 1
    terms += [a for a, n in counts.items() if n >= 2]
    return terms


@dataclass
class Coverage:
    keywords: list[str]
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int | None:
        if not self.keywords:
            return None
        return round(100 * len(self.matched) / len(self.keywords))


def coverage(keywords: list[str], resume_text: str) -> Coverage:
    cov = Coverage(keywords=list(keywords))
    for term in keywords:
        (cov.matched if present(term, resume_text) else cov.missing).append(term)
    return cov
