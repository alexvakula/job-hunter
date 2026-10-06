"""Small in-memory DOCX/PDF samples for resume upload tests."""

import io
import zipfile


def docx_bytes(text: str = "Sam Rivera — QA Lead") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document><w:body>{text}</w:body></w:document>")
    return buf.getvalue()


def pdf_bytes(text: str = "resume") -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\n% " + text.encode() + b"\ntrailer<<>>\n%%EOF\n"


def zip_without_word() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a docx")
    return buf.getvalue()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
