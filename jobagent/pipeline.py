"""The daily run: search -> filter -> score -> assess -> prepare/apply -> network -> announce."""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import digest, insights, notify
from .config import CACHE_DIR, DATA_DIR, Context
from .db import DB
from .llm import LLM, LLMError
from .matching import quick_title_filter, score_job
from .models import Job
from .sources import AGGREGATORS, ATS
from .sources.base import is_uk
from .sponsors import SponsorRegister
from .visa import sponsorship_signal

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    kept: int = 0
    new: int = 0
    shortlisted: int = 0
    assessed: int = 0
    packed: int = 0
    applied: int = 0
    errors: list[str] = field(default_factory=list)


def load_register(ctx: Context, force: bool = False) -> SponsorRegister:
    aliases = ctx.settings["sponsorship"].get("aliases", {})
    return SponsorRegister.load(CACHE_DIR, force=force, aliases=aliases)


def collect(db: DB, ctx: Context, register: SponsorRegister, say: Callable[[str], None] = print) -> RunStats:
    """Fetch jobs from every enabled source and store the relevant ones."""
    st = RunStats()
    want = quick_title_filter(ctx.profile)
    srcs = ctx.settings["sources"]
    uk_only = ctx.settings["search"]["uk_only"]
    max_age = timedelta(days=ctx.settings["search"]["max_age_days"])

    # 1) company boards (seed + discovered + dream companies)
    from .discovery import load_seed
    load_seed(DATA_DIR / "seed_companies.yaml", db)  # picks up companies you add to the seed file
    boards = [b for b in db.live_boards() if srcs.get(b["ats"], False)]
    say(f"Checking {len(boards)} company job boards...")

    # adverts we already hold: slow sources skip them, so repeat runs take a minute or two
    known: dict[str, set] = {}
    for r in db.conn.execute("SELECT source, source_id, extra FROM jobs"):
        known.setdefault(r["source"], set()).add(r["source_id"])
        if r["source"] == "workday":
            path = json.loads(r["extra"] or "{}").get("path")
            if path:
                known.setdefault("workday_paths", set()).add(path)

    def fetch_board(b):
        mod = ATS[b["ats"]]
        if b["ats"] == "smartrecruiters":
            return b, mod.fetch(b["token"], b["company"], uk_only=uk_only, want=want,
                                known=known.get("smartrecruiters"))
        if b["ats"] == "workday":
            return b, mod.fetch(b["token"], b["company"], uk_only=uk_only, want=want,
                                queries=ctx.profile.targets.roles[:4], known=known.get("workday_paths"))
        return b, mod.fetch(b["token"], b["company"], uk_only=uk_only)

    jobs: list[Job] = []
    with cf.ThreadPoolExecutor(8) as ex:
        for fut in cf.as_completed([ex.submit(fetch_board, b) for b in boards]):
            try:
                b, js = fut.result()
                jobs += js
                db.upsert_board(b["ats"], b["token"], b["company"], b["sponsor_name"], "live", len(js))
            except Exception as e:
                st.errors.append(f"board fetch failed: {e}")

    # 2) job-board searches (Reed, Adzuna, NHS Jobs, jobs.ac.uk) with your search queries
    queries = ctx.profile.targets.search_queries or ctx.profile.targets.roles
    locations = [l for l in ctx.profile.targets.locations if "remote" not in l.lower()][:3] or [""]
    for name, mod in AGGREGATORS.items():
        if not srcs.get(name) or not mod.available():
            continue
        # NHS and universities: search by role title (their adverts rarely say "visa sponsorship")
        qs = ctx.profile.targets.roles if name in ("nhs", "jobsacuk") else queries
        locs = [""] if name in ("nhs", "jobsacuk") else locations
        say(f"Searching {name} ({len(qs)} queries x {len(locs)} locations)...")
        for q in qs:
            for loc in locs:
                try:
                    jobs += mod.search(q, loc, want=want, known=known.get(name))
                except Exception as e:
                    st.errors.append(f"{name} '{q}' failed: {e}")

    st.fetched = len(jobs)
    now = datetime.now(timezone.utc)
    for job in jobs:
        if uk_only and job.source not in AGGREGATORS and not is_uk(job.location):
            continue  # (Reed and Adzuna only return UK jobs)
        if job.posted_at:
            posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
            if now - posted > max_age:
                continue
        if not want(job.title):
            continue
        st.kept += 1
        sp = register.match(job.company) or register.match_scaleup(job.company)
        if db.upsert_job(job, sp.name if sp else None):
            st.new += 1
    db.commit()
    say(f"Fetched {st.fetched} jobs, {st.kept} relevant, {st.new} new.")
    return st


def score_all(db: DB, ctx: Context, register: SponsorRegister, only_new: bool = False) -> int:
    rows = db.jobs("status='new'" if only_new else "status IN ('new','shortlisted')", limit=20000)
    thr = ctx.settings["scoring"]["shortlist_threshold"]
    from .learn import current_weights
    weights = current_weights(db, ctx.settings)
    n = 0
    for r in rows:
        job = db.row_to_job(r)
        sp = register.match(job.company)
        su = register.match_scaleup(job.company)
        b = score_job(job, ctx.profile, ctx.settings, sp, weights, scaleup=su)
        db.set_score(job.uid, b.total, b.model_dump_json())
        on_register = sp or su
        db.conn.execute("UPDATE jobs SET sponsor_match=? WHERE uid=?",
                        (on_register.name if on_register else None, job.uid))
        if b.blockers:
            db.conn.execute("UPDATE jobs SET status='skipped' WHERE uid=?", (job.uid,))
        elif b.total >= thr:
            db.conn.execute("UPDATE jobs SET status='shortlisted' WHERE uid=?", (job.uid,))
            n += 1
    db.commit()
    return n


def assess_top(db: DB, ctx: Context, llm: Optional[LLM], limit: Optional[int] = None,
               say: Callable[[str], None] = print) -> int:
    if not llm:
        return 0
    from .assess import assess

    limit = limit or ctx.settings["llm"]["max_assessments_per_run"]
    rows = db.jobs("status='shortlisted' AND assessment_json IS NULL", order="score DESC", limit=limit)
    if rows:
        say(f"Claude is assessing the top {len(rows)} shortlisted jobs...")
    n = 0

    def one(r):
        job = db.row_to_job(r)
        return r, assess(llm, ctx, job, r["sponsor_match"])

    with cf.ThreadPoolExecutor(4) as ex:
        for fut in cf.as_completed([ex.submit(one, r) for r in rows]):
            try:
                r, a = fut.result()
                db.set_assessment(r["uid"], a.fit_score, a.model_dump_json())
                if a.verdict == "skip":
                    db.conn.execute("UPDATE jobs SET status='skipped' WHERE uid=?", (r["uid"],))
                n += 1
            except LLMError as e:
                say(f"  assessment failed: {e}")
    db.commit()
    return n


def watch(db: DB, ctx: Context, llm: Optional[LLM], say: Callable[[str], None] = print) -> list:
    """Quick check for new jobs; pushes "apply today" alerts for the excellent ones."""
    from . import alerts

    register = load_register(ctx)
    st = collect(db, ctx, register, say)
    score_all(db, ctx, register)
    if llm and st.new:
        assess_top(db, ctx, llm, limit=ctx.settings["alerts"]["max_assess_per_watch"], say=say)
    hot = alerts.send(db, ctx, say)
    say(f"{st.new} new jobs, {len(hot)} worth applying to today.")
    db.log("watch", f"new={st.new} hot={len(hot)}")
    return hot


def daily_run(db: DB, ctx: Context, llm: Optional[LLM], apply_mode: Optional[str] = None,
              max_apply: Optional[int] = None, say: Callable[[str], None] = print) -> RunStats:
    from . import inbox, interview, learn, radar
    from .insights import Insight

    extra_insights: list[Insight] = []
    register = load_register(ctx)

    # 1) sponsor radar: new licences since the last register, and their job boards
    rad = radar.update(db, register)
    if rad.first_run:
        say("Sponsor radar: baseline saved. New licences will show up from the next register update.")
    else:
        scan = radar.scan(db, register, ctx.settings["discovery"]["name_keywords"], days=14,
                          max_probes=ctx.settings["radar"]["max_probes_per_run"])
        new_today = len(rad.new)
        say(f"Sponsor radar: {new_today} new sponsors since the last register, "
            f"{len(scan.boards_found)} new job boards found.")
        if scan.boards_found:
            extra_insights.append(Insight(2, f"{len(scan.boards_found)} newly licensed sponsors have job boards",
                                          ", ".join(f"{c} ({n} UK jobs)" for c, _, _, n in scan.boards_found[:6])
                                          + ". They're now in your daily search. New sponsors are often keen to hire."))
        for w in rad.pipeline_warnings:
            extra_insights.append(Insight(1, "Sponsor licence change", w))

    # visa routes: HPI, new-entrant rate, threshold changes (gov.uk pages are cached for a week)
    try:
        from . import visa_routes
        routes = visa_routes.check(ctx.profile, ctx.settings, CACHE_DIR,
                                   scaleup_count=len(register.scaleup.sponsors) if register.scaleup else 0)
        extra_insights += [Insight(p, t, d) for p, t, d in visa_routes.insights_for(routes)]
    except Exception as e:
        log.debug("visa route check failed: %s", e)

    # 2) learn from results so far, then search and score
    if ctx.settings["scoring"].get("adaptive", True):
        learn.learn_weights(db)
    st = collect(db, ctx, register, say)
    st.shortlisted = score_all(db, ctx, register)
    say(f"{st.shortlisted} jobs on the shortlist.")
    st.assessed = assess_top(db, ctx, llm, say=say)

    # prepare packs (and apply, if asked) for the best ones
    mode = apply_mode or ctx.settings["apply"]["mode"]
    max_apply = max_apply if max_apply is not None else ctx.settings["apply"]["max_applications_per_day"]
    thr = ctx.settings["scoring"]["apply_threshold"]
    where = "status='shortlisted' AND fit_score >= ?" if llm else "status='shortlisted' AND score >= ?"
    best = db.jobs(where, (thr,), order="COALESCE(fit_score, score) DESC", limit=max_apply)
    if best and mode != "none":
        from .apply import prepare_and_apply

        for r in best:
            say(f"Preparing {r['title']} at {r['company']}...")
            try:
                out = prepare_and_apply(db, ctx, llm, r["uid"], mode=mode)
                st.packed += 1
                st.applied += int(out.submitted)
                for m in out.messages[-3:]:
                    say(f"  {m}")
            except Exception as e:
                st.errors.append(f"apply failed for {r['company']}: {e}")

    # fresh, excellent jobs: push "apply today"
    from . import alerts
    for r in alerts.send(db, ctx, say):
        t, body = alerts.describe(r)
        extra_insights.append(Insight(1, t, body.replace("\n", ". Run: ")))

    # 3) replies in your inbox: rejections, interview invitations (which get a prep pack)
    if inbox.configured():
        def on_interview(uid):
            row = db.get_job(uid)
            if row:
                path, _ = interview.build_prep(llm, ctx, db, db.row_to_job(row), row["sponsor_match"])
                notify.push(f"Interview: {row['company']}", f"{row['title']}\nPrep pack ready: {path}")
        try:
            for u in inbox.sync(db, ctx, llm, on_interview=on_interview):
                if u.verdict == "offer":
                    extra_insights.append(Insight(1, f"Possible offer from {u.company}",
                                                  f"Email: \"{u.subject}\". Check it, then run `jobagent status <id> offer`."))
                elif u.verdict == "interview":
                    extra_insights.append(Insight(1, f"Interview invitation: {u.company}",
                                                  f"{u.title}. Your prep pack is in the application folder (interview-prep.md)."))
                elif u.verdict == "rejected" and u.applied:
                    st.errors.append(f"Inbox: {u.company} ({u.title}) said no. Marked rejected.")
        except Exception as e:
            st.errors.append(f"Inbox check failed: {e}")

    ins = extra_insights + insights.compute(db, ctx)
    ins.sort(key=lambda i: i.priority)
    notes = st.errors[:10]
    if llm:
        notes.append(f"Claude usage this run: {llm.usage_summary()}")
    md, path = digest.build(db, ctx, ins, st.new, notes)
    say(f"Digest written to {path}")
    top_titles = [f"{r['company']}: {r['title']}" for r in best[:3]]
    if st.new or ins:
        notify.push(f"Job agent: {st.new} new, {st.packed} ready, {st.applied} applied",
                    ("\n".join(top_titles) + "\n\n" + "\n".join(f"- {i.title}" for i in ins[:4])).strip())
        notify.email(f"Job digest: {st.new} new jobs, {st.packed} applications ready", md, digest.to_html(md))
    db.log("run", f"fetched={st.fetched} new={st.new} short={st.shortlisted} assessed={st.assessed} "
                  f"packed={st.packed} applied={st.applied}")
    return st
