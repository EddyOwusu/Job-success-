"""Command line interface: `python -m jobstream <command>` (or `jobstream <command>` once installed)."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import textwrap

import yaml

from . import config
from .config import CONFIG_DIR, DATA_DIR, DB_PATH, ROOT, ensure_dirs, load_context
from .db import DB

STATUSES = ["new", "shortlisted", "skipped", "packed", "applied", "interview", "offer", "rejected", "withdrawn"]


def _ctx_db():
    ensure_dirs()
    ctx = load_context()
    if ctx.using_examples:
        print(f"! Using the EXAMPLE {', '.join(ctx.using_examples)}. Run `jobstream init` and fill in your details.\n")
    return ctx, DB(DB_PATH)


def _llm(ctx):
    from .llm import make_llm

    llm = make_llm(ctx.settings)
    if not llm:
        print("! ANTHROPIC_API_KEY not set: running without Claude (keyword scoring and templates only).")
    return llm


# ---------------------------------------------------------------------------- commands
def cmd_init(a):
    ensure_dirs()
    for name in ("profile", "cv_master"):
        dst = CONFIG_DIR / f"{name}.yaml"
        if dst.exists():
            print(f"  exists   {dst}")
        else:
            shutil.copy(CONFIG_DIR / f"{name}.example.yaml", dst)
            print(f"  created  {dst}  <- fill this in")
    settings = CONFIG_DIR / "settings.yaml"
    if not settings.exists():
        settings.write_text("# Agent settings. Delete anything you don't change; defaults live in jobstream/config.py\n"
                            + yaml.safe_dump(config.DEFAULT_SETTINGS, sort_keys=False), encoding="utf-8")
        print(f"  created  {settings}")
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        print(f"  created  {env}  <- add your API keys")
    print("\nNext: edit those files, then run `jobstream doctor`, `jobstream discover` and `jobstream run`.")


def cmd_doctor(a):
    import os

    ctx, db = _ctx_db()
    ok = lambda b: "OK " if b else "-- "
    print(f"{ok(not ctx.using_examples)}profile + master CV filled in")
    print(f"{ok(ctx.llm_enabled)}ANTHROPIC_API_KEY (Claude: assessment, tailoring, answers, outreach)")
    print(f"{ok(os.environ.get('REED_API_KEY'))}REED_API_KEY (Reed.co.uk search)")
    print(f"{ok(os.environ.get('ADZUNA_APP_ID'))}ADZUNA_APP_ID / ADZUNA_APP_KEY (Adzuna search)")
    print(f"{ok(os.environ.get('HUNTER_API_KEY'))}HUNTER_API_KEY (optional: recruiter emails)")
    print(f"{ok(os.environ.get('NTFY_TOPIC') or os.environ.get('TELEGRAM_BOT_TOKEN'))}push notifications (ntfy / Telegram)")
    print(f"{ok(os.environ.get('SMTP_USER'))}email digest (SMTP)")
    try:
        import playwright  # noqa: F401
        print("OK playwright installed (form filling)")
    except ImportError:
        print("-- playwright missing: pip install playwright && playwright install chromium")
    from .pipeline import load_register
    try:
        reg = load_register(ctx)
        print(f"OK sponsor register: {len(reg.sponsors):,} Skilled Worker sponsors")
    except Exception as e:
        print(f"-- sponsor register: {e}")
    print(f"OK {len(db.live_boards())} company job boards known")


def cmd_sponsors(a):
    ctx, db = _ctx_db()
    from .pipeline import load_register

    reg = load_register(ctx, force=a.update)
    print(f"{len(reg.sponsors):,} Skilled Worker sponsors on the register.")
    for name in a.check or []:
        m = reg.match(name)
        print(f"  {name}: " + (f"YES, '{m.name}' ({m.town}, {m.rating})" if m else "not found (try the legal name)"))


def cmd_discover(a):
    ctx, db = _ctx_db()
    from .discovery import discover, load_seed
    from .pipeline import load_register

    n = load_seed(DATA_DIR / "seed_companies.yaml", db)
    print(f"Loaded {n} seed companies.")
    reg = load_register(ctx)
    kw = ctx.settings["discovery"]["name_keywords"]
    extra = ctx.profile.targets.dream_companies
    max_probes = a.max or ctx.settings["discovery"]["max_probes_per_run"]
    print(f"Probing up to {max_probes} sponsor-register companies for Greenhouse / Lever / Ashby boards...")

    def progress(i, total, name, hits):
        if hits:
            print(f"  [{i}/{total}] FOUND {name}: " + ", ".join(f"{x}/{t} ({c} UK jobs)" for x, t, c in hits))
        elif i % 50 == 0:
            print(f"  [{i}/{total}] ...")

    found = discover(db, reg, kw, max_probes=max_probes, extra_names=extra, progress=progress)
    print(f"\n{len(found)} new job boards at licensed sponsors. {len(db.live_boards())} boards in total.")


def parse_board_url(url: str):
    """(ats, token) from a careers-page URL."""
    import re

    from .sources import workday
    pats = [
        ("greenhouse", r"greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
        ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_-]+)"),
        ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
        ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ]
    tok = workday.parse_url(url)
    if tok:
        return "workday", tok
    for ats, pat in pats:
        m = re.search(pat, url)
        if m and m.group(1) not in ("embed", "v1"):
            return ats, m.group(1)
    return None, None


def cmd_add_board(a):
    ctx, db = _ctx_db()
    from .sources import ATS

    ats, token = parse_board_url(a.url)
    if not ats:
        print("Couldn't recognise that careers site. Supported: Greenhouse, Lever, Ashby, SmartRecruiters, Workday.\n"
              "Tip: open one job on the company's careers page and paste that link; the address shows which system it uses.")
        return 1
    n = ATS[ats].board_exists(token)
    if n is None or n < 0:
        print(f"Found {ats} board '{token}' but it returned no jobs. Check the link.")
        return 1
    from .pipeline import load_register
    sp = load_register(ctx).match(a.name)
    db.upsert_board(ats, token, a.name, sp.name if sp else None, "live", n)
    db.commit()
    import yaml as _y
    seed = DATA_DIR / "seed_companies.yaml"
    with seed.open("a", encoding="utf-8") as f:
        f.write(_y.safe_dump([{"name": a.name, "ats": ats, "token": token}], sort_keys=False))
    print(f"Added {a.name}: {ats} '{token}' ({n} jobs). Sponsor register: " +
          (f"YES ({sp.name})" if sp else "NOT FOUND - only jobs that say they sponsor will be kept"))


def cmd_search(a):
    ctx, db = _ctx_db()
    from .pipeline import collect, load_register, score_all

    reg = load_register(ctx)
    collect(db, ctx, reg)
    n = score_all(db, ctx, reg)
    print(f"{n} jobs on the shortlist. See them with `jobstream list`.")


def cmd_assess(a):
    ctx, db = _ctx_db()
    from .pipeline import assess_top

    llm = _llm(ctx)
    if not llm:
        return 1
    if a.ids:
        rows = [db.get_job(i) for i in a.ids]
        missing = [i for i, r in zip(a.ids, rows) if r is None]
        if missing:
            print("No such job: " + ", ".join(missing))
            return 1
        for r in rows:
            if r["status"] in ("skipped", "new"):
                db.conn.execute("UPDATE jobs SET status='shortlisted' WHERE uid=?", (r["uid"],))
        db.commit()
        print(f"Assessing {len(rows)} jobs...")
        n = assess_top(db, ctx, llm, uids=[r["uid"] for r in rows])
    elif a.again:
        # Claude reads the jobs it already assessed again, e.g. after the rules or your profile changed
        from .prompts import ASSESS_RULES
        rows = db.jobs("assessment_json IS NOT NULL AND status IN ('shortlisted','skipped')",
                       order="COALESCE(fit_score, 0) DESC", limit=5000)
        if not a.all:   # only those read under older rules
            rows = [r for r in rows if json.loads(r["assessment_json"]).get("rules", 1) < ASSESS_RULES]
        rows = rows[: a.limit or ctx.settings["llm"]["max_assessments_per_run"]]
        if not rows:
            print("Every assessment already uses the current rules (add --all to redo them anyway).")
            return
        for r in rows:
            db.conn.execute("UPDATE jobs SET assessment_json=NULL, fit_score=NULL, status='shortlisted' WHERE uid=?",
                            (r["uid"],))
        db.commit()
        print(f"Re-assessing {len(rows)} jobs Claude had already read...")
        n = assess_top(db, ctx, llm, uids=[r["uid"] for r in rows])
    else:
        n = assess_top(db, ctx, llm, limit=a.limit)
    print(f"Assessed {n} jobs ({llm.usage_summary()}). See them with `jobstream list --assessed`.")


def cmd_list(a):
    ctx, db = _ctx_db()
    where, params = "1=1", []
    if a.scaleup:
        rows = [r for r in db.jobs("score_json LIKE '%\"scaleup\":true%' AND status!='skipped'",
                                   order="COALESCE(fit_score, score) DESC", limit=a.limit)]
        if not rows:
            print("No open jobs at Scale-up sponsors yet. Run `jobstream discover` then `jobstream search`.")
            return
        for r in rows:
            print(f"{r['score'] or 0:>5.0f}  {r['status']:<11} {r['company'][:22]:<22} {r['title'][:48]:<48} {r['uid']}")
        return
    if a.assessed:
        rows = db.jobs("assessment_json IS NOT NULL", order="fit_score DESC", limit=a.limit)
        if not rows:
            print("Claude hasn't assessed any jobs yet. Run `jobstream assess` (or `jobstream run`).")
            return
        from .prompts import ASSESS_RULES
        print(f"{'fit':>4}  {'verdict':<22} {'company':<20} {'title':<40} id")
        for r in rows:
            v = json.loads(r["assessment_json"])
            print(f"{r['fit_score'] or 0:>4.0f}  {v.get('verdict', '?'):<22} {r['company'][:20]:<20} {r['title'][:40]:<40} {r['uid']}")
            why = (v.get("red_flags") or []) + (v.get("gaps") or [])
            if why:
                import textwrap
                lines = textwrap.wrap(why[0], 96, max_lines=3, placeholder=" ...")
                print("      why not higher: " + ("\n" + " " * 22).join(lines))
            if v.get("rules", 1) < ASSESS_RULES:
                print("      (read under older rules: `jobstream assess --again` refreshes it)")
        print("\nFull reasoning for one job: jobstream show <id>")
        return
    if a.status:
        where, params = "status=?", [a.status]
    else:
        where = "status IN ('shortlisted','packed','applied','interview','offer')"
    rows = db.jobs(where, params, order="COALESCE(fit_score, score) DESC", limit=a.limit)
    if not rows:
        print("Nothing yet. Run `jobstream search` (or `jobstream run`).")
        return
    print(f"{'fit':>4} {'score':>5}  {'status':<11} {'company':<20} {'title':<45} id")
    for r in rows:
        fit = f"{r['fit_score']:.0f}" if r["fit_score"] is not None else "-"
        print(f"{fit:>4} {r['score'] or 0:>5.0f}  {r['status']:<11} {r['company'][:20]:<20} {r['title'][:45]:<45} {r['uid']}")


def cmd_show(a):
    ctx, db = _ctx_db()
    r = db.get_job(a.id)
    if not r:
        print("No such job (or the id matches several).")
        return 1
    print(f"{r['title']} at {r['company']}\n{r['location']} | {r['url']}\nstatus: {r['status']} | sponsor: {r['sponsor_match'] or 'NOT on register'}")
    if r["score_json"]:
        b = json.loads(r["score_json"])
        print(f"\nScore {b['total']}: skills {b['skills']}, title {b['title']}, seniority {b['seniority']}, "
              f"location {b['location']}, salary {b['salary']}, sponsorship {b['sponsorship']}, freshness {b['freshness']}")
        print(f"Matched: {', '.join(b['matched_skills'])}\nMissing: {', '.join(b['missing_skills'])}")
        for x in b["blockers"]:
            print(f"BLOCKER: {x}")
        for x in b["notes"]:
            print(f"note: {x}")
    if r["assessment_json"]:
        x = json.loads(r["assessment_json"])
        print(f"\nClaude: fit {x['fit_score']} -> {x['verdict']} | sponsorship {x['sponsorship_likelihood']}: {x['sponsorship_evidence']}")
        for k in ("strengths", "gaps", "red_flags", "talking_points"):
            if x.get(k):
                print(f"{k.replace('_', ' ').title()}:")
                for item in x[k]:
                    print(textwrap.fill(item, 100, initial_indent="  - ", subsequent_indent="    "))
    if a.full:
        print("\n" + (r["description"] or ""))


def cmd_apply(a):
    ctx, db = _ctx_db()
    from .apply import prepare_and_apply

    llm = _llm(ctx)
    ids = a.ids
    if a.top:
        thr = ctx.settings["scoring"]["apply_threshold"]
        col = "fit_score" if llm else "score"
        ids = [r["uid"] for r in db.jobs(f"status='shortlisted' AND {col} >= ?", (thr,),
                                         order=f"{col} DESC", limit=a.top)]
        if not ids:
            print(f"No shortlisted jobs with {col} >= {thr}. Run `jobstream assess` or lower scoring.apply_threshold.")
            return
    for uid in ids:
        out = prepare_and_apply(db, ctx, llm, uid, mode=a.mode, force=a.force)
        print("\n".join(f"  {m}" for m in out.messages))
        print(f"  => {'SUBMITTED' if out.submitted else 'not submitted'} ({out.method})\n")


def cmd_mark(a):
    ctx, db = _ctx_db()
    from .apply import mark_applied

    mark_applied(db, ctx, a.id, a.notes or "")
    print("Recorded. Follow-ups scheduled.")


def cmd_status(a):
    ctx, db = _ctx_db()
    r = db.get_job(a.id)
    if not r:
        print("No such job.")
        return 1
    db.set_status(r["uid"], a.status, source="you")
    print(f"{r['company']} / {r['title']} -> {a.status}")
    if a.status == "interview":
        from .interview import build_prep
        print("Building your interview prep pack...")
        path, msgs = build_prep(_llm(ctx), ctx, db, db.row_to_job(r), r["sponsor_match"])
        for m in msgs:
            print(f"  {m}")
        print(f"Open: {path}")


def cmd_prep(a):
    ctx, db = _ctx_db()
    from .interview import build_prep, summary_line

    r = db.get_job(a.id)
    if not r:
        print("No such job.")
        return 1
    path, msgs = build_prep(_llm(ctx), ctx, db, db.row_to_job(r), r["sponsor_match"],
                            stage=a.stage, interviewers=a.interviewers or "", notes=a.notes or "")
    for m in msgs:
        print(f"  {m}")
    print(f"Interview prep ({summary_line(path)}): {path}")


def cmd_dashboard(a):
    ctx, db = _ctx_db()
    from . import dashboard

    path = dashboard.build(db, ctx)
    if not (a.serve or a.lan):
        print(f"Dashboard written: {path}")
        if a.open:
            import webbrowser
            webbrowser.open(path.as_uri())
        else:
            print("Open that file in your browser, or run `jobstream dashboard --open`.\n"
                  "To read it on your phone: `jobstream dashboard --lan` (same Wi-Fi).")
        return

    def page():
        fresh = DB(DB_PATH)          # each request reads the latest data
        try:
            return dashboard.render(dashboard.collect(fresh, ctx))
        finally:
            fresh.conn.close()

    server = dashboard.serve(page, port=a.port, lan=a.lan)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_grow(a):
    ctx, db = _ctx_db()
    from . import growth

    for flag, status in ((a.start, "in_progress"), (a.done, "done"), (a.drop, "dropped")):
        if flag:
            skill = growth.set_status(db, flag, status)
            if not skill:
                print(f"No project planned for '{flag}'. Plan one with `jobstream grow --plan \"{flag}\"`.")
                return 1
            print(f"{skill} -> {status}")
            if status == "done":
                print("\n" + growth.done_snippet(skill))
            return
    gap_list, pool = growth.gaps(db, ctx)
    if not gap_list:
        print(f"Not enough data yet ({pool} near-match jobs; need {growth.MIN_JOBS}). Run `jobstream search` first.")
        return
    if a.plan is not None:
        want = a.plan.lower()
        g = next((g for g in gap_list if g.skill.lower() == want), None) if want else next(
            (g for g in gap_list if not g.status), gap_list[0])
        if not g:
            print(f"'{a.plan}' isn't one of your current gaps. Gaps: " + ", ".join(x.skill for x in gap_list))
            return 1
        print(f"Planning a project for {g.skill}...")
        path = growth.plan(db, ctx, _llm(ctx), g)
        print(f"Plan written: {path}\nStart it with `jobstream grow --start \"{g.skill}\"`.")
        return
    print(f"Skills missing from your profile, across {pool} jobs you nearly match:\n")
    print(f"  {'skill':<18}{'asked in':>9}{'required':>10}{'unlocks':>9}   employers")
    for g in gap_list:
        tag = f"  [{g.status.replace('_', ' ')}]" if g.status else ""
        print(f"  {g.skill:<18}{g.share:>8.0%}{g.required_share:>10.0%}{g.unlocks:>9}   {', '.join(g.employers[:4])}{tag}")
    print("\n'unlocks' = near-miss jobs that would reach your shortlist with that skill.")
    print("Plan a two-week project for the top one with `jobstream grow --plan`, or name one: --plan Kubernetes.")
    print("Already have one of these? Add it to config/profile.yaml instead.")


def cmd_health(a):
    ctx, db = _ctx_db()
    from . import health

    print(health.report(db))


def cmd_speculative(a):
    ctx, db = _ctx_db()
    from . import speculative
    from .pipeline import load_register

    for flag, status in ((a.sent, "sent"), (a.replied, "replied"), (a.close, "closed")):
        if flag:
            ok = speculative.mark(db, flag, status)
            print(f"{flag} -> {status}" if ok else f"No speculative approach found for '{flag}'.")
            if ok and status == "sent":
                print("I'll remind you to send the follow-up in 7 days.")
            return
    reg = load_register(ctx)
    ts = speculative.targets(db, ctx, reg, limit=a.limit)
    if not ts:
        print("No targets yet. Run `jobstream search` first so I know which sponsors use your skills.")
        return
    if a.build:
        room = speculative.weekly_room(db, ctx)
        n = min(a.build, room)
        if n < a.build:
            print(f"Weekly limit: {ctx.settings['speculative']['max_per_week']} approaches a week "
                  f"({room} left). A few specific notes beat many generic ones.")
        llm = _llm(ctx) if n else None
        for t in ts[:n]:
            print(f"Drafting an approach to {t.company}...")
            d = speculative.build(db, ctx, llm, t)
            print(f"  {d}/approach.md")
        return
    print("Sponsors worth approaching even though they have no vacancy that fits you today:\n")
    for i, t in enumerate(ts, 1):
        tag = " [Scale-up]" if t.scaleup else ""
        print(f"{i:>2}. {t.company}{tag}  (score {t.score:.0f})")
        for r in t.reasons:
            print(f"      - {r}")
    waiting = speculative.unsent(db)
    if waiting:
        print("\nDrafted, not sent yet: " + ", ".join(r["company"] for r in waiting))
    print("\nDraft the notes and a CV for the top 3 with `jobstream speculative --build 3`.")


def cmd_watch(a):
    ctx, db = _ctx_db()
    from .pipeline import watch

    watch(db, ctx, _llm(ctx))


def cmd_schedule(a):
    from . import schedule
    from .config import OUTPUT_DIR

    ensure_dirs()
    log = OUTPUT_DIR / "schedule.log"
    if a.remove:
        print(schedule.remove())
        return
    if a.install:
        print(schedule.install(log))
        return
    kind, lines = schedule.plan(log)
    print("The timetable (your computer must be on at these times):\n")
    for name, (freq, at), args, why in schedule.TASKS:
        print(f"  {at}  {'Mondays' if freq == 'WEEKLY' else 'daily  '}  jobstream {args:<16} {why}")
    print("\nRun `jobstream schedule --install` to set it up, or do it yourself with:\n")
    if kind == "cron":
        print("  crontab -e   # then add:")
    for l in lines:
        print(f"  {l}")


def cmd_visa(a):
    ctx, db = _ctx_db()
    from . import visa_routes
    from .config import CACHE_DIR, OUTPUT_DIR
    from .pipeline import load_register

    reg = load_register(ctx)
    routes = visa_routes.check(ctx.profile, ctx.settings, CACHE_DIR,
                               scaleup_count=len(reg.scaleup.sponsors) if reg.scaleup else 0)
    db.set_learned("visa_routes", [{"name": r.name, "status": r.status, "summary": r.summary, "link": r.link}
                                   for r in routes])
    md = visa_routes.report_markdown(routes)
    path = OUTPUT_DIR / "reports" / "visa-routes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"(saved to {path})")


def cmd_radar(a):
    ctx, db = _ctx_db()
    from . import radar
    from .config import OUTPUT_DIR
    from .pipeline import load_register

    reg = load_register(ctx, force=a.update)
    rep = radar.update(db, reg)
    if not rep.first_run and not a.no_probe:
        def progress(i, total, name, hits):
            if hits:
                print(f"  [{i}/{total}] FOUND {name}: " + ", ".join(f"{x}/{t} ({c} UK jobs)" for x, t, c in hits))
        scan = radar.scan(db, reg, ctx.settings["discovery"]["name_keywords"], days=a.days,
                          max_probes=ctx.settings["radar"]["max_probes_per_run"], progress=progress)
        rep.boards_found = scan.boards_found
    md = radar.report_markdown(db, rep, a.days)
    path = OUTPUT_DIR / "radar" / f"radar-{__import__('datetime').date.today():%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    print(md[:3000] + ("\n..." if len(md) > 3000 else ""))
    print(f"(full list saved to {path})")


def cmd_inbox(a):
    ctx, db = _ctx_db()
    from . import inbox
    from .interview import build_prep

    if not inbox.configured():
        print("Set IMAP_USER and IMAP_PASSWORD (or SMTP_USER / SMTP_PASSWORD) in .env. For Gmail, use an App Password "
              "and turn on IMAP in Gmail settings.")
        return 1
    llm = _llm(ctx)

    def on_interview(uid):
        row = db.get_job(uid)
        path, _ = build_prep(llm, ctx, db, db.row_to_job(row), row["sponsor_match"])
        print(f"  Interview prep written: {path}")

    updates = inbox.sync(db, ctx, llm, days=a.days or ctx.settings["inbox"]["days"], on_interview=on_interview)
    if not updates:
        print("No new replies about your applications.")
    for u in updates:
        change = " (status updated)" if u.applied else ""
        print(f"- {u.company} / {u.title}: {u.verdict}{change}  <- \"{u.subject[:80]}\"")


def cmd_learn(a):
    ctx, db = _ctx_db()
    from . import learn
    from .config import OUTPUT_DIR

    rep = learn.report(db)
    weights, notes = learn.learn_weights(db, save=ctx.settings["scoring"].get("adaptive", True))
    md = learn.report_markdown(rep, notes)
    path = OUTPUT_DIR / "reports" / "whats-working.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"(saved to {path})")


def cmd_network(a):
    ctx, db = _ctx_db()
    from . import networking

    r = db.get_job(a.id)
    if not r:
        print("No such job.")
        return 1
    plan = networking.build_plan(_llm(ctx), ctx, db.row_to_job(r), r["sponsor_match"])
    print(networking.plan_markdown(plan))


def cmd_followups(a):
    ctx, db = _ctx_db()
    if a.done:
        db.complete_followup(a.done)
        print("Done.")
        return
    due = db.due_followups()
    if not due:
        print("No follow-ups due. Nice.")
    for d in due:
        print(f"[{d['id']}] {d['due']}  {d['company']} / {d['title']}: {d['message']}")
    if due:
        print("\nMark one done with `jobstream followups --done <id>`. Messages are in each application's networking.md.")


def cmd_insights(a):
    ctx, db = _ctx_db()
    from .insights import compute

    for i in compute(db, ctx):
        print(textwrap.fill(f"[{'!' * (4 - i.priority)}] {i.title}: {i.detail}", 100, subsequent_indent="    "))


def cmd_digest(a):
    ctx, db = _ctx_db()
    from . import digest
    from .insights import compute

    md, path = digest.build(db, ctx, compute(db, ctx), 0, [])
    print(md)
    print(f"(saved to {path})")


def cmd_run(a):
    ctx, db = _ctx_db()
    from .pipeline import daily_run

    st = daily_run(db, ctx, _llm(ctx), apply_mode=a.mode, max_apply=a.max_apply)
    print(f"\nDone: {st.new} new, {st.shortlisted} shortlisted, {st.assessed} assessed, {st.packed} packs, "
          f"{st.applied} submitted.")
    for e in st.errors[:10]:
        print(f"  ! {e}")


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobstream", description="JobStream: your personal UK tech job-search agent.")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log", metavar="FILE", help="append everything printed to this file (used by scheduled runs)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create your config files").set_defaults(fn=cmd_init)
    sub.add_parser("doctor", help="check configuration and API keys").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("sponsors", help="update the sponsor register / check employers")
    s.add_argument("--update", action="store_true", help="download today's register")
    s.add_argument("--check", nargs="*", help="company names to look up")
    s.set_defaults(fn=cmd_sponsors)
    s = sub.add_parser("discover", help="find job boards of licensed sponsors")
    s.add_argument("--max", type=int, help="companies to probe this time")
    s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("add-board", help="add any company's careers site (Greenhouse/Lever/Ashby/SmartRecruiters/Workday)")
    s.add_argument("name", help="company name, e.g. 'Guy\'s and St Thomas\' NHS Foundation Trust'")
    s.add_argument("url", help="link to the careers page or one of its jobs")
    s.set_defaults(fn=cmd_add_board)
    sub.add_parser("search", help="fetch and score jobs").set_defaults(fn=cmd_search)
    s = sub.add_parser("assess", help="deep Claude assessment of the shortlist")
    s.add_argument("ids", nargs="*", help="assess (or re-assess) exactly these jobs")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--again", action="store_true", help="re-assess jobs Claude read under older rules")
    s.add_argument("--all", action="store_true", help="with --again: redo every assessment (e.g. after a profile change)")
    s.set_defaults(fn=cmd_assess)
    s = sub.add_parser("list", help="show the shortlist and pipeline")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--scaleup", action="store_true", help="only jobs at Scale-up sponsors")
    s.add_argument("--assessed", action="store_true", help="every job Claude has read, with its verdict and why")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("show", help="details of one job")
    s.add_argument("id")
    s.add_argument("--full", action="store_true", help="print the advert too")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("apply", help="tailor CV + letter, then fill/submit the application")
    s.add_argument("ids", nargs="*")
    s.add_argument("--top", type=int, help="apply to the N best shortlisted jobs")
    s.add_argument("--mode", choices=["pack", "dry", "review", "auto"],
                   help="pack: files only | dry: fill a hidden browser + screenshot, never submit | "
                        "review: you press Submit | auto: submits when confident")
    s.add_argument("--force", action="store_true", help="ignore daily / per-company limits")
    s.set_defaults(fn=cmd_apply)
    s = sub.add_parser("mark-applied", help="record an application you sent by hand")
    s.add_argument("id")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_mark)
    s = sub.add_parser("status", help="update a job's status (interview, offer, rejected...)")
    s.add_argument("id")
    s.add_argument("status", choices=STATUSES)
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("prep", help="interview prep pack for a job (also built automatically on 'status <id> interview')")
    s.add_argument("id")
    s.add_argument("--stage", default="first interview", help="e.g. 'recruiter screen', 'technical', 'final panel'")
    s.add_argument("--interviewers", help="names and roles, if you know them")
    s.add_argument("--notes", help="anything they told you about the interview")
    s.set_defaults(fn=cmd_prep)
    s = sub.add_parser("dashboard", help="one page with today's actions, shortlist, pipeline, results and source health")
    s.add_argument("--open", action="store_true", help="open it in your browser")
    s.add_argument("--serve", action="store_true", help="serve it live on this computer (refresh to update)")
    s.add_argument("--lan", action="store_true", help="also reachable from your phone on the same Wi-Fi")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_dashboard)
    s = sub.add_parser("grow", help="your skill gaps, and two-week project plans that close them")
    s.add_argument("--plan", nargs="?", const="", metavar="SKILL", help="write a project plan (top gap if no skill given)")
    s.add_argument("--start", metavar="SKILL")
    s.add_argument("--done", metavar="SKILL", help="finished: shows what to add to your profile and master CV")
    s.add_argument("--drop", metavar="SKILL")
    s.set_defaults(fn=cmd_grow)
    sub.add_parser("health", help="is every job source still working?").set_defaults(fn=cmd_health)
    s = sub.add_parser("speculative", help="sponsors worth approaching without a vacancy; drafts the note and CV")
    s.add_argument("--build", type=int, metavar="N", help="draft approach packs for the top N")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--sent", metavar="COMPANY", help="you sent it: start the follow-up clock")
    s.add_argument("--replied", metavar="COMPANY")
    s.add_argument("--close", metavar="COMPANY")
    s.set_defaults(fn=cmd_speculative)
    sub.add_parser("watch", help="quick check for fresh jobs; pushes 'apply today' alerts (schedule a few times a day)").set_defaults(fn=cmd_watch)
    s = sub.add_parser("schedule", help="show or install the daily timetable (Windows Task Scheduler or cron)")
    s.add_argument("--install", action="store_true", help="create the scheduled tasks now")
    s.add_argument("--remove", action="store_true", help="remove them")
    s.set_defaults(fn=cmd_schedule)
    sub.add_parser("visa", help="which visa routes are open to you (Skilled Worker, Scale-up, HPI...), checked on gov.uk").set_defaults(fn=cmd_visa)
    s = sub.add_parser("radar", help="newly licensed visa sponsors, and their job boards")
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--update", action="store_true", help="download today's register first")
    s.add_argument("--no-probe", action="store_true", help="don't check new sponsors for job boards")
    s.set_defaults(fn=cmd_radar)
    s = sub.add_parser("inbox", help="read replies to your applications and update statuses")
    s.add_argument("--days", type=int)
    s.set_defaults(fn=cmd_inbox)
    sub.add_parser("learn", help="what's working: interview rates by sector, source, score... and tuned scoring").set_defaults(fn=cmd_learn)
    s = sub.add_parser("network", help="who to contact and what to say for a job")
    s.add_argument("id")
    s.set_defaults(fn=cmd_network)
    s = sub.add_parser("followups", help="follow-ups that are due")
    s.add_argument("--done", type=int, help="mark a follow-up as done")
    s.set_defaults(fn=cmd_followups)
    sub.add_parser("insights", help="the agent's suggestions").set_defaults(fn=cmd_insights)
    sub.add_parser("digest", help="write today's digest").set_defaults(fn=cmd_digest)
    s = sub.add_parser("run", help="the full daily loop (use this from cron)")
    s.add_argument("--mode", choices=["none", "pack", "review", "auto"], help="what to do with the best matches")
    s.add_argument("--max-apply", type=int)
    s.set_defaults(fn=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.log:
        from datetime import datetime
        from pathlib import Path
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(args.log, "a", encoding="utf-8", buffering=1)
        print(f"\n=== {datetime.now():%Y-%m-%d %H:%M} jobstream {args.cmd} ===")
    else:
        # Windows consoles and pipes may not be UTF-8; never crash on a job title with an emoji in it
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.fn(args) or 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
