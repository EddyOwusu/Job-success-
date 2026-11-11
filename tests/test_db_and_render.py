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


def test_duplicates_across_boards_with_different_place_text(tmp_path):
    db = DB(tmp_path / "d.db")
    a = Job(source="reed", source_id="1", company="Scania  Limited", title="IT Second Line Analyst", location="Milton Keynes")
    b = Job(source="adzuna", source_id="2", company="Scania Limited", title="IT Second Line Analyst",
            location="Milton Keynes, Buckinghamshire")
    c = Job(source="adzuna", source_id="3", company="Scania Limited", title="IT Second Line Analyst", location="Glasgow")
    assert db.upsert_job(a, None) and not db.upsert_job(b, None) and db.upsert_job(c, None)
    assert db.get_job("reed:1")["company"] == "Scania Limited"          # spacing tidied
    assert len(db.jobs()) == 2                                           # Milton Keynes once, Glasgow kept


def test_merge_existing_duplicates(tmp_path):
    db = DB(tmp_path / "m.db")
    for i, loc in enumerate(["Milton Keynes", "Milton Keynes, Buckinghamshire", "Leeds"]):
        db.conn.execute("INSERT INTO jobs (uid, source, source_id, company, title, location, fingerprint, first_seen, status) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (f"x:{i}", "x", str(i), "Scania", "Analyst", loc, "scania|analyst",
                                                       f"2026-11-1{i}", "shortlisted"))
    db.commit()
    assert db.merge_duplicates() == 1
    assert sorted(r["uid"] for r in db.jobs()) == ["x:0", "x:2"]


def test_agency_jobs_get_no_sponsor_credit(profile, settings):
    from datetime import datetime, timezone

    from jobstream.agencies import is_agency
    from jobstream.matching import score_job
    from jobstream.sponsors import Sponsor
    sp = Sponsor("Robert Half Ltd", "London", "", "Worker (A rating)", "Skilled Worker")
    j = Job(source="reed", source_id="9", company="Robert Half", title="IT Support Engineer", location="Cambridge",
            description="Requirements\n- Microsoft 365, Active Directory", posted_at=datetime.now(timezone.utc))
    assert is_agency(j.company, j.extra) and not is_agency("Scania Limited")
    assert not is_agency("Robert Half", {"agency": False})               # Reed's own flag wins
    direct = score_job(j, profile, settings, sp)
    agency = score_job(j, profile, settings, sp, agency=True)
    assert agency.sponsorship < 0.3 < direct.sponsorship
    assert not agency.blockers and any("recruitment agency" in n for n in agency.notes)


def test_legal_suffixes_do_not_split_duplicates(tmp_path):
    from jobstream.db import fingerprint
    assert fingerprint("Renishaw PLC", "IT Support") == fingerprint("Renishaw", "IT  support")
    assert fingerprint("Candour Solutions Limited", "x") == fingerprint("Candour Solutions", "x")
    assert fingerprint("Co-op", "x") != fingerprint("Op", "x")           # "co" is not a legal suffix
    db = DB(tmp_path / "s.db")
    # rows stored with the old key are re-keyed and merged
    for i, co in enumerate(["Renishaw", "Renishaw PLC"]):
        db.conn.execute("INSERT INTO jobs (uid, source, source_id, company, title, location, fingerprint, first_seen, status) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (f"r:{i}", "r", str(i), co, "IT Analyst", "Wotton-under-Edge",
                                                       co.lower() + "|it analyst", f"2026-11-1{i}", "shortlisted"))
    db.commit()
    assert db.merge_duplicates() == 1 and [r["uid"] for r in db.jobs()] == ["r:0"]


def test_recruiter_divisions_are_agencies():
    from jobstream.agencies import is_agency
    for name in ["Hays Technology", "Reed Technology", "Oscar Technology", "Reed", "MCS Group", "Randstad Digital",
                 "Civic Recruitment Limited", "VIQU Limited"]:
        assert is_agency(name), name
    for name in ["Reed Elsevier", "Hays Travel", "Renishaw PLC", "BDO", "Giacom", "East Suffolk Council", "Oscar Health"]:
        assert not is_agency(name), name
