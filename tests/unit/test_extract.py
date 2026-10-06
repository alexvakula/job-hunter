import json
from pathlib import Path

import pytest

from jobhunter.services.extract import JobDraft, from_html, from_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())
FIELDS = (
    "title",
    "company",
    "location",
    "work_mode",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
)


def _extract(name: str) -> JobDraft:
    content = (FIXTURES / name).read_text()
    if name.startswith("pages/"):
        return from_html(content, "https://example.test/job")
    return from_text(content)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_extraction(name):
    draft = _extract(name)
    expected = EXPECTED[name]
    for field in FIELDS:
        assert getattr(draft, field) == expected[field], (name, field)
    assert expected["description_contains"] in draft.description


def test_html_description_has_no_tags():
    draft = _extract("pages/jobbank.html")
    assert "<" not in draft.description
    assert "Plan tests" in draft.description


@pytest.mark.parametrize("junk", ["", "   ", "<<<>>>", "<script>{not json</script>", "\x00\x01"])
def test_bad_input_never_raises(junk):
    assert isinstance(from_html(junk, "https://x.test"), JobDraft)
    assert isinstance(from_text(junk), JobDraft)


def test_text_description_is_full_text():
    text = (FIXTURES / "texts/range_dollars.txt").read_text()
    assert from_text(text).description == text.strip()


def test_salary_with_cents_and_thousands_range():
    from jobhunter.services.extract import parse_salary

    s = parse_salary("$140,000.00 to $150,000.00 annually")
    assert (s["salary_min"], s["salary_max"], s["salary_period"]) == (140000, 150000, "year")
