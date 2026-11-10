import json
from datetime import date, datetime, timedelta, timezone

import pytest

from jobagent import inbox, interview, learn, radar
from jobagent.config import Context
from jobagent.db import DB
from jobagent.models import Job
from jobagent.sponsors import from_csv_text

HEAD = "Organisation Name,Town/City,County,Type & Rating,Route\n"
DAY1 = HEAD + """Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker
Old Corp Ltd,Leeds,,Worker (A rating),Skilled Worker
Shaky Ltd,Leeds,,Worker (A rating),Skilled Worker
"""
DAY2 = HEAD + """Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker
Shaky Ltd,Leeds,,Worker (B rating),Skilled Worker
Brand New Robotics Ltd,Cambridge,,Worker (A rating),Skilled Worker
"""


def add_job(db, uid, company, status, sponsor=None, extra=None, score=None, fit=None, posted=None):
    j = Job(source="greenhouse", source_id=uid, company=company, title="Backend Engineer", location="London",
            posted_at=posted, extra=extra or {})
    db.upsert_job(j, sponsor)
    db.conn.execute("UPDATE jobs SET status=?, score=?, fit_score=?, score_json=? WHERE uid=?",
                    (status, score, fit, json.dumps({"skills": 0.8, "title": 1, "seniority": 0.7, "location": 1,
                                                     "salary": 1, "sponsorship": 1, "freshness": 1, "blockers": []}),
                     j.uid))
    db.commit()
    return j.uid


# ---------------------------------------------------------------------------- radar
def test_radar_detects_new_removed_downgraded(tmp_path):
    db = DB(tmp_path / "r.db")
    first = radar.update(db, from_csv_text(DAY1), date(2026, 11, 9))
    assert first.first_run and not first.new
    add_job(db, "1", "Old Corp", "applied", sponsor="Old Corp Ltd")
    add_job(db, "2", "Shaky", "interview", sponsor="Shaky Ltd")
    rep = radar.update(db, from_csv_text(DAY2), date(2026, 11, 10))
    assert [s.name for s in rep.new] == ["Brand New Robotics Ltd"]
    assert rep.removed == ["Old Corp Ltd"]
    assert rep.downgraded == ["Shaky Ltd"]
    assert any("Old Corp" in w and "no longer" in w for w in rep.pipeline_warnings)
    assert any("Shaky" in w and "B rating" in w for w in rep.pipeline_warnings)
    # the baseline is never reported as "new"
    assert [r["name"] for r in radar.recent_new(db, 30)] == ["Brand New Robotics Ltd"]
    # running again the same day changes nothing
    again = radar.update(db, from_csv_text(DAY2), date(2026, 11, 10))
    assert not again.new and not again.removed


# ---------------------------------------------------------------------------- learn
def seed_apps(db, n_pos_nhs=5, n_neg_tech=15):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).isoformat()
    for i in range(n_pos_nhs + n_neg_tech):
        nhs = i < n_pos_nhs
        uid = add_job(db, f"a{i}", f"Co{i}", "interview" if nhs else "rejected", sponsor="X",
                      extra={"sector": "nhs" if nhs else "tech"}, score=75 if nhs else 62, fit=80 if nhs else 60)
        feats = {"sector": "nhs" if nhs else "tech", "source": "nhs" if nhs else "greenhouse", "claude": True,
                 "score": 75 if nhs else 62, "fit": 80 if nhs else 60, "days_old": 1 if nhs else 10,
                 "salary_known": nhs, "components": {"skills": 0.9 if nhs else 0.5, "title": 0.9, "seniority": 0.7,
                                                     "location": 1, "salary": 1 if nhs else 0.5,
                                                     "sponsorship": 1, "freshness": 1 if nhs else 0.4}}
        db.conn.execute("INSERT INTO applications (job_uid, company, title, applied_at, method, features, status) "
                        "VALUES (?,?,?,?,?,?,?)", (uid, f"Co{i}", "Backend Engineer", old, "manual",
                                                   json.dumps(feats), "x"))
    db.commit()


def test_learning_report_and_weights(tmp_path):
    db = DB(tmp_path / "l.db")
    seed_apps(db)
    rep = learn.report(db)
    assert rep.total == 20 and rep.positive == 5 and rep.negative == 15
    sector = {g.label: g for g in rep.breakdowns["Sector"]}
    assert sector["NHS"].rate == 1.0 and sector["TECH"].rate == 0.0
    assert any("Sector" in f and "NHS" in f for f in rep.findings)
    weights, notes = learn.learn_weights(db)
    assert abs(sum(weights.values()) - 100) < 0.5
    assert weights["skills"] > 35 and weights["freshness"] > 5      # these predicted interviews
    assert db.get_learned("weights") == weights
    assert "Sector" in learn.report_markdown(rep, notes)


def test_learning_waits_for_enough_data(tmp_path):
    db = DB(tmp_path / "l2.db")
    seed_apps(db, n_pos_nhs=1, n_neg_tech=5)
    weights, notes = learn.learn_weights(db)
    assert weights == learn.WEIGHTS and "Need" in notes[0]
    assert db.get_learned("weights") is None


def test_snapshot_records_features(tmp_path):
    db = DB(tmp_path / "s.db")
    uid = add_job(db, "1", "Acme", "packed", sponsor="Acme Ltd", extra={"sector": "university"}, score=70,
                  posted=datetime.now(timezone.utc) - timedelta(days=2))
    f = learn.snapshot(db.get_job(uid), method="browser-review", claude=True)
    assert f["sector"] == "university" and f["days_old"] == 2 and f["on_register"] and f["components"]["skills"] == 0.8


# ---------------------------------------------------------------------------- inbox
def mail(subject, body, sender="Talent Team", addr="no-reply@us.greenhouse-mail.io", mid="m1"):
    return inbox.Mail(mid, sender, addr, subject, body, "")


@pytest.mark.parametrize("subject,body,verdict", [
    ("Your application to Monzo", "Unfortunately we have decided not to progress your application.", "rejected"),
    ("Next steps", "We'd like to invite you to an interview. Please share your availability.", "interview"),
    ("Thanks for applying", "We have received your application for Backend Engineer.", "ack"),
    ("Offer", "We are pleased to offer you the role of Backend Engineer.", "offer"),
    ("Hello", "Just checking in.", "unclear"),
])
def test_classify(subject, body, verdict):
    assert inbox.classify(mail(subject, body)) == verdict


def test_match_and_sync(tmp_path, monkeypatch, profile, cv, settings):
    db = DB(tmp_path / "i.db")
    uid_monzo = add_job(db, "1", "Monzo", "applied", sponsor="Monzo Bank Ltd")
    uid_nhs = add_job(db, "2", "University Hospital Southampton NHS Trust", "applied")
    for u in (uid_monzo, uid_nhs):
        db.conn.execute("INSERT INTO applications (job_uid, company, title, applied_at, method) VALUES (?,?,?,?,?)",
                        (u, "x", "Backend Engineer", datetime.now(timezone.utc).isoformat(), "manual"))
    db.commit()
    mails = [
        mail("Your Monzo application", "Unfortunately we won't be moving forward.", mid="a"),
        mail("Backend Engineer - interview", "Southampton team would like to invite you to an interview",
             sender="NHS Jobs", addr="noreply@jobs.nhs.uk", mid="b"),
        mail("Your newsletter", "Unfortunately the sale has ended", sender="Shop", addr="news@shop.com", mid="c"),
    ]
    monkeypatch.setattr(inbox, "fetch", lambda days=30: mails)
    called = []
    ups = inbox.sync(db, Context(profile, cv, settings), None, on_interview=called.append)
    verdicts = {u.company: u.verdict for u in ups}
    assert verdicts == {"Monzo": "rejected", "University Hospital Southampton NHS Trust": "interview"}
    assert db.get_job(uid_monzo)["status"] == "rejected"
    assert db.get_job(uid_nhs)["status"] == "interview" and called == [uid_nhs]
    # already-read emails are not processed twice
    assert inbox.sync(db, Context(profile, cv, settings), None) == []


# ---------------------------------------------------------------------------- interview prep
class FakeLLM:
    def research(self, prompt, **kw):
        assert "Jane" not in prompt          # personal details never go to web research
        return "Acme builds payment rails. Interviews: screen, technical, values.", [("Acme blog", "https://acme.example/blog")]

    def structured(self, *, system, prompt, schema, **kw):
        assert "Acme builds payment rails" in prompt
        c = interview.Concern(concern="Cost of sponsorship", answer="It's a known, one-off process.")
        return schema(
            process_overview="Screen, technical, values panel.", company_brief=["Payment rails for UK banks"],
            tell_me_about_yourself="I build Python APIs...", why_this_role="Your payments scale...",
            questions=[interview.PrepQuestion(category="technical", question="Design an idempotent payment API",
                                              why_they_ask="Core of the job", answer_outline=["Idempotency keys"])],
            technical_topics=[interview.TopicPlan(topic="Idempotency", why_it_matters_here="Payments",
                                                  what_to_revise=["Keys"], practice="Design one")],
            stories=[interview.StarStory(title="Outage", situation="s", task="t", action="a", result="r", use_for=["pressure"])],
            sponsorship=interview.SponsorshipTalk(when_to_raise="With the recruiter", script="I'll need sponsorship...",
                                                  likely_concerns=[c], facts_to_have_ready=["£41,700 threshold"]),
            salary_script="My range is...", gaps_to_prepare_for=[c], questions_to_ask=["What's hard this year?"],
            checklist=["Test the link"])


def test_build_prep(tmp_path, monkeypatch, profile, cv, settings):
    monkeypatch.setattr(interview, "OUTPUT_DIR", tmp_path)
    db = DB(tmp_path / "p.db")
    job = Job(source="greenhouse", source_id="1", company="Acme", title="Backend Engineer", description="Python APIs")
    path, msgs = interview.build_prep(FakeLLM(), Context(profile, cv, settings), db, job, "Acme Ltd")
    md = path.read_text()
    for section in ("## Likely questions", "## Your stories (STAR)", "## Talking about sponsorship",
                    "## Questions to ask them", "## Sources", "https://acme.example/blog"):
        assert section in md
    assert interview.summary_line(path) == "1 questions, 1 stories, 1 topics"


def test_template_prep(tmp_path, monkeypatch, profile, cv, settings):
    monkeypatch.setattr(interview, "OUTPUT_DIR", tmp_path)
    db = DB(tmp_path / "t.db")
    job = Job(source="nhs", source_id="1", company="Trust", title="Developer",
              description="Requirements\n- Python and SQL\nNice to have\n- Kubernetes")
    path, msgs = interview.build_prep(None, Context(profile, cv, settings), db, job, None)
    md = path.read_text()
    assert "Python (required)" in md and "Kubernetes (nice to have)" in md and "Payments outage" in md
