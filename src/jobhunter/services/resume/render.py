"""ATS-safe resume and cover letter as DOCX and PDF (FR-009, FR-010).

One column, standard headings, plain paragraphs and bullet lists only: no tables, images, text
boxes or header/footer text. PDFs use bundled DejaVu fonts so any Unicode text renders.
"""

import io
from pathlib import Path

from docx import Document
from docx.shared import Pt
from fpdf import FPDF

FONTS = Path(__file__).resolve().parents[2] / "fonts"
HEADINGS = ("Summary", "Experience", "Education", "Certifications", "Skills")


def _contact_line(c: dict) -> str:
    return " | ".join(
        p for p in [c.get("email"), c.get("phone"), c.get("location"), *c.get("links", [])] if p
    )


def _dates(e: dict) -> str:
    start, end = e.get("start", ""), e.get("end", "")
    return f"{start} – {end}" if start and end else start or end


def _sections(c: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(heading, [(kind, text)])] where kind is 'line', 'bold' or 'bullet'."""
    out = []
    if c.get("summary"):
        out.append(("Summary", [("line", c["summary"])]))
    exp = []
    for e in c.get("experience", []):
        exp.append(("bold", " — ".join(p for p in (e.get("title"), e.get("employer")) if p)))
        meta = " | ".join(p for p in (e.get("location"), _dates(e)) if p)
        if meta:
            exp.append(("line", meta))
        exp += [("bullet", b) for b in e.get("bullets", [])]
    if exp:
        out.append(("Experience", exp))
    edu = []
    for e in c.get("education", []):
        cred = ", ".join(p for p in (e.get("credential"), e.get("field")) if p)
        edu.append(("bold", " — ".join(p for p in (cred, e.get("institution")) if p)))
        if _dates(e):
            edu.append(("line", _dates(e)))
    if edu:
        out.append(("Education", edu))
    certs = [
        ("bullet", ", ".join(p for p in (x.get("name"), x.get("issuer"), x.get("date")) if p))
        for x in c.get("certifications", [])
    ]
    if certs:
        out.append(("Certifications", certs))
    if c.get("skills"):
        out.append(("Skills", [("line", ", ".join(c["skills"]))]))
    return out


def resume_docx(c: dict) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    name = doc.add_paragraph()
    run = name.add_run(c.get("name") or "")
    run.bold, run.font.size = True, Pt(18)
    if _contact_line(c):
        doc.add_paragraph(_contact_line(c))
    for heading, items in _sections(c):
        doc.add_heading(heading, level=1)
        for kind, text in items:
            if kind == "bullet":
                doc.add_paragraph(text, style="List Bullet")
            elif kind == "bold":
                doc.add_paragraph().add_run(text).bold = True
            else:
                doc.add_paragraph(text)
    return _save(doc)


def letter_docx(c: dict, letter: str) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    if c.get("name"):
        doc.add_paragraph().add_run(c["name"]).bold = True
    if _contact_line(c):
        doc.add_paragraph(_contact_line(c))
    for para in _paragraphs(letter):
        doc.add_paragraph(para)
    return _save(doc)


def _save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _paragraphs(text: str) -> list[str]:
    paras, current = [], []
    for line in (text or "").splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            paras.append(" ".join(current))
            current = []
    if current:
        paras.append(" ".join(current))
    return paras


class _Pdf(FPDF):
    def __init__(self):
        super().__init__(format="Letter")
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, margin=16)
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.add_page()

    def text_block(self, text: str, size: float = 10.5, bold: bool = False, gap: float = 1.2):
        self.set_font("DejaVu", "B" if bold else "", size)
        self.multi_cell(0, size * 0.5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(gap)


def resume_pdf(c: dict) -> bytes:
    pdf = _Pdf()
    pdf.text_block(c.get("name") or "", size=18, bold=True)
    if _contact_line(c):
        pdf.text_block(_contact_line(c), size=10)
    for heading, items in _sections(c):
        pdf.ln(2)
        pdf.text_block(heading, size=13, bold=True, gap=0.5)
        for kind, text in items:
            if kind == "bullet":
                pdf.text_block("• " + text)
            else:
                pdf.text_block(text, bold=kind == "bold", gap=0.6)
    return bytes(pdf.output())


def letter_pdf(c: dict, letter: str) -> bytes:
    pdf = _Pdf()
    if c.get("name"):
        pdf.text_block(c["name"], size=14, bold=True, gap=0.5)
    if _contact_line(c):
        pdf.text_block(_contact_line(c), size=10, gap=4)
    for para in _paragraphs(letter):
        pdf.text_block(para, size=11, gap=3)
    return bytes(pdf.output())
