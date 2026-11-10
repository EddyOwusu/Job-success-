"""Render CVs and cover letters as ATS-friendly DOCX, PDF and Markdown.

ATS rules followed: one column, standard section headings, real text (no images,
tables, text boxes, headers/footers holding contact details), common fonts,
simple bullets, dates as "Jan 2023 - Present".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import CoverLetter, Personal, TailoredCV

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(s: str) -> str:
    s = (s or "").strip()
    if s.lower() in ("present", "now", "current", ""):
        return "Present"
    parts = s.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{MONTHS[int(parts[1]) - 1]} {parts[0]}"
    return s


def contact_line(p: Personal) -> str:
    bits = [p.location, p.phone, p.email, p.linkedin, p.github, p.portfolio]
    return " | ".join(b.replace("https://", "").replace("www.", "") for b in bits if b)


# ---------------------------------------------------------------------------- markdown
def cv_markdown(cv: TailoredCV, p: Personal) -> str:
    out = [f"# {p.full_name}", cv.headline, "", contact_line(p), "", "## Summary", cv.summary, "",
           "## Skills", ", ".join(cv.skills), "", "## Experience"]
    for r in cv.experience:
        out += ["", f"### {r.title}, {r.company}", f"{r.location} | {fmt_date(r.start)} - {fmt_date(r.end)}"]
        out += [f"- {b}" for b in r.bullets]
    if cv.projects:
        out += ["", "## Projects"] + [f"- {x}" for x in cv.projects]
    if cv.education:
        out += ["", "## Education"] + [f"- {x}" for x in cv.education]
    if cv.certifications:
        out += ["", "## Certifications"] + [f"- {x}" for x in cv.certifications]
    return "\n".join(out) + "\n"


def letter_markdown(cl: CoverLetter, p: Personal, company: str) -> str:
    head = [p.full_name, contact_line(p), date.today().strftime("%d %B %Y"), "", company, "", cl.greeting, ""]
    return "\n".join(head + [x + "\n" for x in cl.paragraphs] + [cl.sign_off]) + "\n"


# ---------------------------------------------------------------------------- docx
def cv_docx(cv: TailoredCV, p: Personal, path: Path) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(1.6)
        s.left_margin = s.right_margin = Cm(1.9)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    style.paragraph_format.space_after = Pt(2)

    def heading(text: str) -> None:
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(8)
        para.paragraph_format.space_after = Pt(2)
        run = para.add_run(text.upper())
        run.bold = True
        run.font.size = Pt(11.5)

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = name.add_run(p.full_name)
    r.bold = True
    r.font.size = Pt(18)
    doc.add_paragraph(cv.headline).runs[0].font.size = Pt(11.5)
    doc.add_paragraph(contact_line(p))

    heading("Summary")
    doc.add_paragraph(cv.summary)
    heading("Skills")
    doc.add_paragraph(", ".join(cv.skills))
    heading("Experience")
    for role in cv.experience:
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(5)
        t = para.add_run(f"{role.title}, {role.company}")
        t.bold = True
        doc.add_paragraph(f"{role.location} | {fmt_date(role.start)} - {fmt_date(role.end)}").runs[0].italic = True
        for b in role.bullets:
            doc.add_paragraph(b, style="List Bullet")
    for title, items in (("Projects", cv.projects), ("Education", cv.education), ("Certifications", cv.certifications)):
        if items:
            heading(title)
            for x in items:
                doc.add_paragraph(x, style="List Bullet")
    doc.core_properties.author = p.full_name
    doc.core_properties.title = f"{p.full_name} CV"
    doc.save(path)
    return path


def letter_docx(cl: CoverLetter, p: Personal, company: str, path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_paragraph(p.full_name).runs[0].bold = True
    doc.add_paragraph(contact_line(p))
    doc.add_paragraph(date.today().strftime("%d %B %Y"))
    doc.add_paragraph(company)
    doc.add_paragraph(cl.greeting)
    for para in cl.paragraphs:
        doc.add_paragraph(para)
    for line in cl.sign_off.split("\n"):
        doc.add_paragraph(line)
    doc.save(path)
    return path


# ---------------------------------------------------------------------------- pdf
def _pdf(story_fn, path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.9 * cm, rightMargin=1.9 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm)
    doc.build(story_fn())
    return path


def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=10, leading=13)
    return {
        "base": base,
        "name": ParagraphStyle("name", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21),
        "h": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=11, spaceBefore=8, spaceAfter=3),
        "role": ParagraphStyle("role", parent=base, fontName="Helvetica-Bold", spaceBefore=5),
        "meta": ParagraphStyle("meta", parent=base, fontName="Helvetica-Oblique"),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=12, bulletIndent=2),
    }


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cv_pdf(cv: TailoredCV, p: Personal, path: Path) -> Path:
    from reportlab.platypus import Paragraph

    st = _styles()

    def story():
        s = [Paragraph(_esc(p.full_name), st["name"]), Paragraph(_esc(cv.headline), st["base"]),
             Paragraph(_esc(contact_line(p)), st["base"]),
             Paragraph("SUMMARY", st["h"]), Paragraph(_esc(cv.summary), st["base"]),
             Paragraph("SKILLS", st["h"]), Paragraph(_esc(", ".join(cv.skills)), st["base"]),
             Paragraph("EXPERIENCE", st["h"])]
        for r in cv.experience:
            s.append(Paragraph(_esc(f"{r.title}, {r.company}"), st["role"]))
            s.append(Paragraph(_esc(f"{r.location} | {fmt_date(r.start)} - {fmt_date(r.end)}"), st["meta"]))
            s += [Paragraph(_esc(b), st["bullet"], bulletText="•") for b in r.bullets]
        for title, items in (("PROJECTS", cv.projects), ("EDUCATION", cv.education), ("CERTIFICATIONS", cv.certifications)):
            if items:
                s.append(Paragraph(title, st["h"]))
                s += [Paragraph(_esc(x), st["bullet"], bulletText="•") for x in items]
        return s

    return _pdf(story, path)


def letter_pdf(cl: CoverLetter, p: Personal, company: str, path: Path) -> Path:
    from reportlab.platypus import Paragraph, Spacer

    st = _styles()

    def story():
        s = [Paragraph(_esc(p.full_name), st["role"]), Paragraph(_esc(contact_line(p)), st["base"]),
             Paragraph(date.today().strftime("%d %B %Y"), st["base"]), Spacer(1, 8),
             Paragraph(_esc(company), st["base"]), Spacer(1, 8), Paragraph(_esc(cl.greeting), st["base"]), Spacer(1, 6)]
        for para in cl.paragraphs:
            s += [Paragraph(_esc(para), st["base"]), Spacer(1, 6)]
        s += [Paragraph(_esc(line), st["base"]) for line in cl.sign_off.split("\n")]
        return s

    return _pdf(story, path)
