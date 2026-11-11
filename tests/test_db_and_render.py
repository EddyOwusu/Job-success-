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


def test_same_advert_text_merges_even_when_places_differ(tmp_path):
    db = DB(tmp_path / "t.db")
    body = ("Renishaw is a global engineering company. We are looking for a Manufacturing IT Support Analyst to "
            "support our production sites, looking after Windows endpoints, Microsoft 365 and shop-floor systems. ") * 3
    a = Job(source="adzuna", source_id="1", company="Renishaw", title="Manufacturing IT Support Analyst",
            location="Wotton-under-Edge", description=body)
    b = Job(source="adzuna", source_id="2", company="Renishaw PLC", title="Manufacturing IT Support Analyst",
            location="Stonehouse, Gloucestershire", description=body.replace("global", "global,"))
    c = Job(source="adzuna", source_id="3", company="Renishaw", title="Manufacturing IT Support Analyst",
            location="Miskin, Wales", description="A different advert for our Welsh site. " * 10)
    assert db.upsert_job(a, None) and not db.upsert_job(b, None) and db.upsert_job(c, None)


def test_sponsor_names_that_only_share_a_first_word():
    from jobstream.sponsors import SponsorRegister
    rows = [{"Organisation Name": n, "Route": "Skilled Worker", "Type & Rating": "Worker (A rating)"}
            for n in ["Sage Care Ltd", "The Sage Group plc", "Candour Care Group Ltd", "Bupa Care Services Limited",
                      "Barts Health NHS Trust", "Acme Digital Services Ltd"]]
    reg = SponsorRegister(rows)
    assert reg.match("Sage").name == "The Sage Group plc"            # corporate form beats a care business
    assert reg.match("Candour Solutions") is None                     # "solutions" is not "care group"
    assert reg.match("Bupa").name == "Bupa Care Services Limited"
    assert reg.match("Barts Health NHS Foundation Trust").name == "Barts Health NHS Trust"
    assert reg.match("Acme Services UK").name == "Acme Digital Services Ltd"


def test_full_text_from_job_page():
    from jobstream.fulltext import from_html
    ld = ('<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization"},'
          '{"@type":"JobPosting","title":"Service Desk Analyst","description":"&lt;p&gt;Full advert&lt;/p&gt;'
          '&lt;ul&gt;&lt;li&gt;Microsoft 365&lt;/li&gt;&lt;/ul&gt;"}]}</script></html>')
    text = from_html(ld)
    assert "Full advert" in text and "- Microsoft 365" in text
    adz = '<html><section class="adp-body mx-4">About the role<p>Look after 300 users.</p></section></html>'
    assert "300 users" in from_html(adz)
    assert from_html("<html><p>nothing here</p></html>") == ""


def test_assessment_prompt_knows_relocation_and_current_employer(profile, cv, settings):
    from jobstream.assess import assess
    from jobstream.config import Context
    from jobstream.models import FitAssessment

    seen = {}

    class LLM:
        def structured(self, *, system, prompt, schema, **kw):
            seen["prompt"] = prompt
            return FitAssessment(fit_score=70, verdict="apply", sponsorship_likelihood="high", sponsorship_evidence="",
                                 salary_meets_visa_threshold="yes", seniority_match="ok", strengths=[], gaps=[],
                                 red_flags=[], talking_points=[], keywords_to_mirror=[])

    profile.targets.locations = ["Anywhere in the UK", "Remote (UK)"]
    profile.visa.willing_to_relocate = True
    current = next(r for r in cv.experience if r.end in ("", "present"))
    job = Job(source="adzuna", source_id="1", company=current.company + " Ltd", title="Service Desk Analyst",
              location="Hull", description="Support 300 users.")
    assess(LLM(), Context(profile, cv, settings), job, None)
    assert "relocate anywhere in the UK" in seen["prompt"]
    assert "internal applicant" in seen["prompt"]
    assert "Silence on sponsorship is normal" in seen["prompt"]
