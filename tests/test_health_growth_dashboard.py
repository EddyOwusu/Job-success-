import json
from datetime import datetime, timezone

from jobagent import dashboard, growth, health
from jobagent.config import Context
from jobagent.db import DB
from jobagent.models import Job
from jobagent.skills import extract_skills, extract_weighted


class J:
    def __init__(self, description="x" * 300):
        self.description = description


def run(db, at, rows):
    for kind, key, seen, jobs, err in rows:
        health.record(db, at, kind, key, seen, jobs, err)
    db.commit()


# ---------------------------------------------------------------------------- health
def test_health_detects_breakage(tmp_path):
    db = DB(tmp_path / "h.db")
    boards = [("greenhouse", f"co{i}", 20, [J()], None) for i in range(6)]
    ok = boards + [("nhs", "", 200, [J()] * 3, None), ("jobsacuk", "", 150, [], None), ("lever", "a", 9, [], None), ("lever", "b", 4, [], None)]
    run(db, "2026-11-09T07:00:00", ok)
    assert {s.state for s in health.status(db)} == {"new"} and health.insights(db) == []
    run(db, "2026-11-10T07:00:00", ok)
    assert {s.state for s in health.status(db)} == {"ok"}

    broken = ([("greenhouse", f"co{i}", 0 if i < 4 else 20, [], None) for i in range(6)]        # 4 of 6 boards empty
              + [("nhs", "", 0, [], None),                                                       # API changed
                 ("jobsacuk", "", 0, [], "ConnectionError: boom"),                               # every query failed
                 ("lever", "a", 9, [], None), ("lever", "b", 4, [], None)])
    run(db, "2026-11-11T07:00:00", broken)
    st = {s.kind: s for s in health.status(db)}
    assert st["greenhouse"].state == "broken" and "4 of 6" in st["greenhouse"].detail
    assert st["nhs"].state == "broken" and "usually returns about 200" in st["nhs"].detail
    assert st["jobsacuk"].state == "broken" and st["lever"].state == "ok"
    titles = [i.title for i in health.insights(db)]
    assert "NHS Jobs looks broken" in titles and all(i.priority == 1 for i in health.insights(db))
    assert "BROKEN NHS Jobs" in health.report(db)


def test_health_single_board_moved_and_empty_adverts(tmp_path):
    db = DB(tmp_path / "h2.db")
    base = [("ashby", f"co{i}", 10, [], None) for i in range(5)]
    run(db, "2026-11-01T07:00:00", base)
    for day in ("02", "03", "04"):                       # one board goes quiet for three runs
        run(db, f"2026-11-{day}T07:00:00", [("ashby", "co0", 0, [], None)] + base[1:])
    st = health.status(db)[0]
    assert st.state == "warn" and st.moved == ["co0"]
    # adverts returned without their text
    db2 = DB(tmp_path / "h3.db")
    run(db2, "2026-11-01T07:00:00", [("nhs", "", 100, [J()] * 6, None)])
    run(db2, "2026-11-02T07:00:00", [("nhs", "", 100, [J("")] * 6, None)])
    assert health.status(db2)[0].state == "warn" and "without their full text" in health.status(db2)[0].detail


def test_health_offline_is_one_message(tmp_path):
    db = DB(tmp_path / "h4.db")
    kinds = ["greenhouse", "nhs", "jobsacuk"]
    run(db, "2026-11-01T07:00:00", [("greenhouse", "a", 5, [], None), ("greenhouse", "b", 5, [], None), ("nhs", "", 9, [], None), ("jobsacuk", "", 9, [], None)])
    run(db, "2026-11-02T07:00:00", [("greenhouse", "a", 0, [], "ConnectionError"), ("greenhouse", "b", 0, [], "ConnectionError"),
                                    ("nhs", "", 0, [], "ConnectionError"), ("jobsacuk", "", 0, [], "ConnectionError")])
    ins = health.insights(db)
    assert len(ins) == 1 and "offline" in ins[0].detail and len(kinds) == 3


# ---------------------------------------------------------------------------- skills + growth
def test_generic_words_are_not_skills():
    assert "Security" not in extract_skills("We are a security-first company with great job security")
    assert "Security" in extract_skills("Experience with OWASP and threat modelling")
    assert "Testing" not in extract_skills("We do A/B testing of the product")
    assert "Testing" in extract_skills("You write unit tests and care about test coverage")
    w = extract_weighted("Backend Engineer (Python)\nWe are an AI company doing machine learning.\nRequirements\n- Django\nNice to have\n- Kubernetes")
    assert w == {"Python": 1.0, "Machine Learning": 0.3, "Django": 1.0, "Kubernetes": 0.4}


def seed_jobs(db, n=12):
    for i in range(n):
        desc = "Requirements\n- Python, Django\n- Kubernetes in production\n" + ("Nice to have\n- Terraform\n" if i % 2 else "")
        j = Job(source="greenhouse", source_id=str(i), company=f"Co{i % 4}", title="Backend Engineer", location="London",
                description=desc)
        db.upsert_job(j, "X Ltd")
        db.conn.execute("UPDATE jobs SET score=?, score_json=?, status='new' WHERE uid=?",
                        (55 if i < 6 else 70, json.dumps({"title": 1.0, "blockers": [], "notes": []}), j.uid))
    db.commit()


def test_gaps_and_project_plan(tmp_path, monkeypatch, profile, cv, settings):
    monkeypatch.setattr(growth, "OUTPUT_DIR", tmp_path)
    db = DB(tmp_path / "g.db")
    ctx = Context(profile, cv, settings)
    assert growth.gaps(db, ctx) == ([], 0)
    seed_jobs(db)
    gap_list, pool = growth.gaps(db, ctx)
    assert pool == 12 and [g.skill for g in gap_list] == ["Kubernetes", "Terraform"]
    k = gap_list[0]
    assert k.share == 1.0 and k.required_share == 1.0 and k.unlocks == 6 and "Co0" in k.employers
    assert "Python" not in [g.skill for g in gap_list]            # you already have it

    path = growth.plan(db, ctx, None, k)
    md = path.read_text()
    assert "## Two-week plan" in md and "Kubernetes" in md and "[ ]" in md
    assert growth.gaps(db, ctx)[0][0].status == "planned"
    assert growth.set_status(db, "kubernetes", "done") == "Kubernetes"
    assert growth.active(db) == []
    assert "name: Kubernetes" in growth.done_snippet("Kubernetes")
    assert growth.set_status(db, "Fortran", "done") is None


# ---------------------------------------------------------------------------- dashboard
def test_dashboard_builds_and_escapes(tmp_path, monkeypatch, profile, cv, settings):
    db = DB(tmp_path / "d.db")
    ctx = Context(profile, cv, settings)
    j = Job(source="greenhouse", source_id="1", company="Evil </script><script>alert(1)</script> Ltd",
            title="Backend Engineer", location="London", url="javascript:alert(1)",
            posted_at=datetime.now(timezone.utc))
    db.upsert_job(j, "X Ltd")
    db.conn.execute("UPDATE jobs SET status='shortlisted', score=80, score_json=? WHERE uid=?",
                    (json.dumps({"blockers": [], "notes": [], "matched_skills": ["Python"], "title": 1.0}), j.uid))
    db.commit()
    data = dashboard.collect(db, ctx)
    assert data["counts"]["shortlisted"] == 1 and data["shortlist"][0]["matched"] == ["Python"]
    page = dashboard.render(data)
    assert page.startswith("<!doctype html>") and "Job search dashboard" in page
    assert "</script><script>alert(1)" not in page            # job text can't break out of the data block
    assert json.loads(page.split('id="data">')[1].split("</script>")[0].replace("<\\/", "</"))["shortlist"][0]["title"] == "Backend Engineer"
    frag = dashboard.render(data, standalone=False)
    assert "<!doctype" not in frag and frag.startswith("<title>")
    out = dashboard.build(db, ctx, tmp_path / "dash.html")
    assert out.stat().st_size > 5000


def test_dashboard_server_needs_the_token():
    import threading
    import urllib.error
    import urllib.request

    server = dashboard.serve(lambda: "<p>hello</p>", port=0, lan=False, token="secret123", announce=lambda *_: None)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/secret123").read() == b"<p>hello</p>"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            assert False, "should be 404 without the token"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()
