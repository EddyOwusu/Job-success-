from jobstream.db import DB
from jobstream.models import CoverLetter, Job, TailoredCV, TailoredRole
from jobstream import render


def test_dedupe_across_sources(tmp_path):
    db = DB(tmp_path / "t.db")
    a = Job(source="greenhouse", source_id="1", company="Acme", title="Backend Engineer", location="London")
    b = Job(source="reed", source_id="99", company="ACME", title="Backend  Engineer", location="London")
    assert db.upsert_job(a, "Acme Ltd") is True
    assert db.upsert_job(a, "Acme Ltd") is False
    assert db.upsert_job(b, "Acme Ltd") is False
    assert len(db.jobs()) == 1


def test_render_files(tmp_path, profile):
    cv = TailoredCV(headline="Engineer", summary="Hi", skills=["Python"], projects=[], education=["BSc"],
                    certifications=[], experience=[TailoredRole(company="A & B", title="Dev", location="X",
                                                                start="2023-01", end="present", bullets=["Did <things>"])])
    p = profile.personal
    assert render.cv_docx(cv, p, tmp_path / "cv.docx").stat().st_size > 1000
    assert render.cv_pdf(cv, p, tmp_path / "cv.pdf").stat().st_size > 1000
    cl = CoverLetter(greeting="Dear Hiring Team,", paragraphs=["One", "Two"], sign_off="Kind regards,\nJane")
    assert render.letter_pdf(cl, p, "Acme", tmp_path / "cl.pdf").exists()
    assert "Jan 2023 - Present" in render.cv_markdown(cv, p)


def test_cli_parser():
    from jobstream.cli import build_parser
    args = build_parser().parse_args(["apply", "--top", "3", "--mode", "review"])
    assert args.top == 3 and args.mode == "review"


def test_other_employment_section(tmp_path, profile):
    cv = TailoredCV(headline="IT Support", summary="Hi", skills=["Microsoft 365"], projects=[], education=[], certifications=[],
                    experience=[TailoredRole(company="Acme", title="IT Lead", location="London", start="2025-04", end="present",
                                             bullets=["Ran Microsoft 365"]),
                                TailoredRole(company="Bupa", title="Senior Carer", location="Barnet", start="2026-10",
                                             end="present", bullets=[], kind="other")])
    md = render.cv_markdown(cv, profile.personal)
    assert "## Other employment" in md and "- Senior Carer, Bupa, Barnet | Oct 2026 - Present" in md
    assert md.index("IT Lead") < md.index("## Other employment")
    assert render.cv_docx(cv, profile.personal, tmp_path / "cv.docx").exists()
    assert render.cv_pdf(cv, profile.personal, tmp_path / "cv.pdf").exists()
