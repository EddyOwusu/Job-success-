import json
from datetime import date, datetime, timedelta, timezone

from jobagent import alerts, schedule, speculative, visa_routes
from jobagent.config import Context
from jobagent.db import DB
from jobagent.matching import score_job
from jobagent.models import Job
from jobagent.sponsors import from_csv_text

CSV = """Organisation Name,Town/City,County,Type & Rating,Route
Rocket Labs Ltd,London,,Worker (A rating),Scale-up
Rocket Labs Ltd,London,,Worker (A rating),Skilled Worker
OnlyScale Ltd,Leeds,,Worker (A rating),Scale-up
Steady Bank Plc,London,,Worker (A rating),Skilled Worker
"""
DESC = "Requirements\n- Python, Django, PostgreSQL, Docker, AWS\nWe build payments APIs."


def job(company, title="Backend Engineer", **kw):
    base = dict(source="greenhouse", source_id=f"{company}-{title}", company=company, title=title, location="London, UK",
                description=DESC, posted_at=datetime.now(timezone.utc))
    base.update(kw)
    return Job(**base)


# ---------------------------------------------------------------------------- Scale-up
def test_scaleup_register_and_scoring(profile, settings):
    reg = from_csv_text(CSV)
    assert reg.match_scaleup("Rocket Labs").name == "Rocket Labs Ltd"
    assert reg.match("OnlyScale") is None and reg.match_scaleup("OnlyScale") is not None
    assert reg.match_scaleup("Steady Bank") is None
    # Scale-up-only employer is not blocked as "not on the register"
    b = score_job(job("OnlyScale"), profile, settings, reg.match("OnlyScale"), scaleup=reg.match_scaleup("OnlyScale"))
    assert not b.blockers and b.scaleup and any("Scale-up" in n for n in b.notes)
    # £40k: under the Skilled Worker minimum, over the Scale-up minimum
    b = score_job(job("Rocket Labs", salary_min=39500, salary_max=40000), profile, settings,
                  reg.match("Rocket Labs"), scaleup=reg.match_scaleup("Rocket Labs"))
    assert not b.blockers
    b = score_job(job("Steady Bank", salary_min=39500, salary_max=40000), profile, settings, reg.match("Steady Bank"))
    assert any("threshold" in x for x in b.blockers)


# ---------------------------------------------------------------------------- visa routes
LISTS = {2023: [("University of Toronto", "Canada"), ("Massachusetts Institute of Technology (MIT)", "United States")],
         2024: [("University of Toronto", "Canada")]}


def test_hpi_matching():
    assert visa_routes.hpi_match("University of Toronto", LISTS, [2023]) == {2023: "University of Toronto"}
    assert visa_routes.hpi_match("MIT", LISTS, [2023])[2023].startswith("Massachusetts")
    assert visa_routes.hpi_match("University of Ghana", LISTS, [2023, 2024]) == {2023: None, 2024: None}


def routes_for(profile, settings, tmp_path, monkeypatch, **changes):
    monkeypatch.setattr(visa_routes, "hpi_lists", lambda cache: LISTS)
    monkeypatch.setattr(visa_routes, "live_thresholds", lambda cache: {"general": 41700, "new_entrant": 33400, "scaleup": 39100})
    monkeypatch.setattr(visa_routes, "_guide", lambda slug, cache: {"eligibility": "Canada Australia Japan"})
    for k, v in changes.items():
        obj, attr = k.split("__")
        setattr(getattr(profile, obj), attr, v)
    return {r.name: r for r in visa_routes.check(profile, settings, tmp_path, scaleup_count=93, today=date(2026, 11, 10))}


def test_route_check_hpi_and_new_entrant(profile, settings, tmp_path, monkeypatch):
    r = routes_for(profile, settings, tmp_path, monkeypatch, education__institution="University of Toronto",
                   education__graduation_year=2024, education__graduation_month=6,
                   visa__date_of_birth="2002-03-01", visa__nationality="Canadian")
    assert r["High Potential Individual (HPI)"].status == "likely"
    assert any("under 26" in d for d in r["Skilled Worker"].details)
    assert "Youth Mobility Scheme" in r
    titles = [t for _, t, _ in visa_routes.insights_for(list(r.values()))]
    assert any("HPI" in t for t in titles) and any("new-entrant" in t for t in titles)


def test_route_check_not_eligible_cases(profile, settings, tmp_path, monkeypatch):
    r = routes_for(profile, settings, tmp_path, monkeypatch)            # graduated 2021: over 5 years ago
    assert r["High Potential Individual (HPI)"].status == "not_eligible"
    r = routes_for(profile, settings, tmp_path, monkeypatch, education__uk_degree=True, education__graduation_year=2025)
    assert r["High Potential Individual (HPI)"].status == "not_eligible" and "Graduate visa" in r
    r = routes_for(profile, settings, tmp_path, monkeypatch, education__institution="University of Ghana",
                   education__graduation_year=2024, education__uk_degree=False)
    assert r["High Potential Individual (HPI)"].status == "unlikely"


def test_threshold_drift_is_reported(profile, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(visa_routes, "hpi_lists", lambda cache: LISTS)
    monkeypatch.setattr(visa_routes, "live_thresholds", lambda cache: {"general": 43000, "new_entrant": 33400, "scaleup": 39100})
    routes = visa_routes.check(profile, settings, tmp_path, today=date(2026, 11, 10))
    assert any("gov.uk now says £43,000" in d for d in routes[0].details)
    assert any("threshold has changed" in t for _, t, _ in visa_routes.insights_for(routes))


# ---------------------------------------------------------------------------- speed alerts
def store(db, j, status="shortlisted", score=80, fit=None, first_seen=None, sponsor="X Ltd", extra_score=None):
    db.upsert_job(j, sponsor)
    sj = {"notes": [], "blockers": [], "scaleup": False, **(extra_score or {})}
    db.conn.execute("UPDATE jobs SET status=?, score=?, fit_score=?, score_json=?, first_seen=COALESCE(?, first_seen) WHERE uid=?",
                    (status, score, fit, json.dumps(sj), first_seen, j.uid))
    db.commit()


def test_hot_alerts_once_only(tmp_path, monkeypatch, profile, cv, settings):
    db = DB(tmp_path / "a.db")
    ctx = Context(profile, cv, settings)
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    store(db, job("Fresh", "Backend Engineer"), score=80)                                   # hot (no Claude score)
    store(db, job("Great", "Python Developer"), score=70, fit=90)                           # hot (Claude fit)
    store(db, job("Meh", "Software Engineer"), score=80, fit=70)                            # Claude says no
    store(db, job("Stale", "Data Engineer"), score=90, first_seen=old)                      # found days ago
    store(db, job("OldPost", "Full Stack Engineer", posted_at=datetime.now(timezone.utc) - timedelta(days=9)), score=90)
    store(db, job("Blocked", "Backend Engineer II"), status="skipped", score=95)
    pushed = []
    monkeypatch.setattr(alerts.notify, "push", lambda title, body, url="": pushed.append(title) or [])
    hot = alerts.send(db, ctx, say=lambda *_: None)
    assert sorted(r["company"] for r in hot) == ["Fresh", "Great"]
    assert len(pushed) == 2 and all(t.startswith("Apply today:") for t in pushed)
    assert alerts.send(db, ctx, say=lambda *_: None) == []                                  # never twice


def test_schedule_plans():
    lines = schedule.cron_lines(__import__("pathlib").Path("/tmp/x.log"))
    assert len(lines) == 5 and lines[0].startswith("10 7 * * * ") and " 1 " in lines[-1] and "watch" in lines[1]
    cmds = schedule.windows_commands()
    assert all(c.startswith("schtasks /Create") for c in cmds) and cmds[-1].endswith("/D MON")


# ---------------------------------------------------------------------------- speculative
def test_speculative_targets_and_pack(tmp_path, monkeypatch, profile, cv, settings):
    monkeypatch.setattr(speculative, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(speculative.networking, "company_domain", lambda j: "rocketlabs.example")
    db = DB(tmp_path / "s.db")
    ctx = Context(profile, cv, settings)
    reg = from_csv_text(CSV)
    senior = {"notes": ["Title level 'staff' vs your target ['junior', 'mid']"]}
    store(db, job("Rocket Labs", "Staff Backend Engineer"), status="new", score=40, extra_score=senior)
    store(db, job("Rocket Labs", "Principal Engineer"), status="new", score=30, extra_score=senior)
    store(db, job("Rocket Labs", "Staff Platform Engineer"), status="new", score=35, extra_score=senior)
    store(db, job("Steady Bank", "Backend Engineer"), status="shortlisted")                 # real vacancy: excluded
    store(db, job("Unlicensed Co", "Staff Engineer"), status="new", sponsor=None)           # not a sponsor: excluded
    store(db, job("OnlyScale", "Lead Engineer", description=DESC + "\nWe are unable to sponsor visas."), status="skipped")
    store(db, job("Uni", "Senior Developer", extra={"sector": "university"}), status="new")
    ts = speculative.targets(db, ctx, reg)
    assert [t.company for t in ts] == ["Rocket Labs"]
    t = ts[0]
    assert t.scaleup and "Python" in t.stack
    assert any("more senior" in r for r in t.reasons) and any("Scale-up" in r for r in t.reasons)

    d = speculative.build(db, ctx, None, t)
    md = (d / "approach.md").read_text()
    assert "## Email" in md and "sponsor licence" in md and "first.last@rocketlabs.example" in md
    assert list(d.glob("*-cv.docx")) and list(d.glob("*-cv.pdf"))
    assert speculative.targets(db, ctx, reg) == []                                          # not suggested again
    assert speculative.weekly_room(db, ctx) == settings["speculative"]["max_per_week"] - 1
    assert [r["company"] for r in speculative.unsent(db)] == ["Rocket Labs"]

    assert speculative.mark(db, "rocket", "sent")
    db.conn.execute("UPDATE speculative SET sent_at=?", ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),))
    db.commit()
    assert [r["company"] for r in speculative.due_followups(db)] == ["Rocket Labs"]
    assert speculative.mark(db, "Rocket Labs", "replied") and speculative.due_followups(db) == []
