import pytest

from jobhunter.services.resumes import MAX_BYTES, UploadError, detect_format, sanitize_name
from tests.resume_samples import PNG, docx_bytes, pdf_bytes, zip_without_word


def test_detects_pdf_and_docx_by_content():
    assert detect_format(pdf_bytes()) == "pdf"
    assert detect_format(docx_bytes()) == "docx"


@pytest.mark.parametrize(
    "data", [b"", b"plain text resume", PNG, zip_without_word(), b"PK\x03\x04broken zip"]
)
def test_rejects_other_content(data):
    with pytest.raises(UploadError):
        detect_format(data)


def test_size_limit_is_10_mb():
    assert MAX_BYTES == 10 * 1024 * 1024


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Resume.docx", "Resume.docx"),
        ("C:\\Users\\sam\\My Resume.pdf", "My Resume.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("bad\x00name\n.pdf", "badname.pdf"),
        ("", "resume"),
        ("a" * 300 + ".pdf", "a" * 196 + ".pdf"),
    ],
)
def test_sanitize_name(raw, expected):
    assert sanitize_name(raw) == expected
