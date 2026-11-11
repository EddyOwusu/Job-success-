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
from .llm import LLM, BudgetReached, LLMError
from .matching import quick_title_filter, score_job
from .models import FitAssessment, Job
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

    from . import health
    run_at = health.new_run()

    def fetch_board(b):
        mod = ATS[b["ats"]]
        stats: dict = {}
        try:
            if b["ats"] == "smartrecruiters":
                js = mod.fetch(b["token"], b["company"], uk_only=uk_only, want=want,
                               known=known.get("smartrecruiters"), stats=stats)
            elif b["ats"] == "workday":
                js = mod.fetch(b["token"], b["company"], uk_only=uk_only, want=want,
                               queries=ctx.profile.targets.roles[:4], known=known.get("workday_paths"), stats=stats)
            else:
                js = mod.fetch(b["token"], b["company"], uk_only=uk_only, stats=stats)
            return b, js, stats, None
        except Exception as e:
            return b, [], stats, f"{e.__class__.__name__}: {e}"[:200]

    jobs: list[Job] = []
    with cf.ThreadPoolExecutor(8) as ex:
        for fut in cf.as_completed([ex.submit(fetch_board, b) for b in boards]):
            b, js, stats, err = fut.result()
            jobs += js
            health.record(db, run_at, b["ats"], b["token"], stats.get("seen", 0), js, err)
            if err:
                st.errors.append(f"{b['company']} ({b['ats']}) failed: {err}")
            else:
                db.upsert_board(b["ats"], b["token"], b["company"], b["sponsor_name"], "live", len(js))

    # 2) job-board searches (Reed, Adzuna, NHS Jobs, jobs.ac.uk) with your search queries
    queries = ctx.profile.targets.search_queries or ctx.profile.targets.roles
    # Reed and Adzuna search by place; "Anywhere in the UK" (or no places listed) searches the whole country
    if ctx.profile.targets.anywhere:
        locations = [""]
    else:
        locations = [l for l in ctx.profile.targets.locations if "remote" not in l.lower()][:3] or [""]
    for name, mod in AGGREGATORS.items():
        if not srcs.get(name) or not mod.available():
            continue
        # NHS and universities: search by role title (their adverts rarely say "visa sponsorship")
        qs = ctx.profile.targets.roles if name in ("nhs", "jobsacuk") else queries
        locs = [""] if name in ("nhs", "jobsacuk") else locations
        say(f"Searching {name} ({len(qs)} queries x {len(locs)} locations)...")
        stats, got, errs = {}, [], []
        for q in qs:
            for loc in locs:
                try:
                    got += mod.search(q, loc, want=want, known=known.get(name), stats=stats)
                except Exception as e:
                    errs.append(f"{e.__class__.__name__}: {e}"[:200])
                    st.errors.append(f"{name} '{q}' failed: {e}")
        jobs += got
        # an error only counts against the source if every query failed
        health.record(db, run_at, name, "", stats.get("seen", 0), got,
                      errs[0] if errs and len(errs) == len(qs) * len(locs) else None)

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
        from .agencies import is_agency
        sp = None if is_agency(job.company, job.extra) else (register.match(job.company) or register.match_scaleup(job.company))
        if db.upsert_job(job, sp.name if sp else None):
            st.new += 1
    db.commit()
    merged = db.merge_duplicates()
    say(f"Fetched {st.fetched} jobs, {st.kept} relevant, {st.new} new." + (f" Merged {merged} duplicates." if merged else ""))
    return st


def score_all(db: DB, ctx: Context, register: SponsorRegister, only_new: bool = False) -> int:
    rows = db.jobs("status='new'" if only_new else "status IN ('new','shortlisted')", limit=20000)
    thr = ctx.settings["scoring"]["shortlist_threshold"]
    from .learn import current_weights
    weights = current_weights(db, ctx.settings)
    n = 0
    for r in rows:
        job = db.row_to_job(r)
        from .agencies import is_agency
        agency = is_agency(job.company, job.extra)
        sp = None if agency else register.match(job.company)
        su = None if agency else register.match_scaleup(job.company)
        b = score_job(job, ctx.profile, ctx.settings, sp, weights, scaleup=su, agency=agency)
        db.set_score(job.uid, b.total, b.model_dump_json())
        on_register = sp or su
        db.conn.execute("UPDATE jobs SET sponsor_match=? WHERE uid=?",
                        (on_register.name if on_register else None, job.uid))
        if b.blockers:
            db.conn.execute("UPDATE jobs SET status='skipped' WHERE uid=?", (job.uid,))
        elif b.total >= thr:
            db.conn.execute("UPDATE jobs SET status='shortlisted' WHERE uid=?", (job.uid,))
            n += 1
        elif r["status"] == "shortlisted":     # fell below the bar after a rule change (e.g. now known as an agency)
            db.conn.execute("UPDATE jobs SET status='new' WHERE uid=?", (job.uid,))
    db.commit()
    return n


def _pending_batches(db: DB) -> list[dict]:
    return db.get_learned("assess_batches", []) or []


def _waiting_uids(db: DB) -> set[str]:
    return {u for b in _pending_batches(db) for u in b["map"].values()}


def assess_top(db: DB, ctx: Context, llm: Optional[LLM], limit: Optional[int] = None,
               say: Callable[[str], None] = print, fresh_only: bool = False, uids: Optional[list[str]] = None,
               batch: bool = False) -> int:
    """Claude reads the best unassessed shortlisted jobs. fresh_only: just the new, alert-worthy ones.
    uids: exactly these jobs. batch: send them as one Message Batch (half price; results come later and
    are stored by harvest_batches). Returns how many were assessed (or, with batch, sent)."""
    if not llm:
        return 0
    from .assess import assess

    limit = limit or ctx.settings["llm"]["max_assessments_per_run"]
    if uids is not None:
        rows = [r for r in (db.get_job(u) for u in uids) if r is not None]
    elif fresh_only:
        a = ctx.settings["alerts"]
        since = (datetime.now(timezone.utc) - timedelta(hours=a["max_age_hours"])).isoformat()
        rows = db.jobs("status='shortlisted' AND assessment_json IS NULL AND sponsor_match IS NOT NULL "
                       "AND first_seen >= ? AND score >= ?", (since, a["hot_score"]), order="score DESC", limit=limit)
        if rows:
            say(f"Claude is checking {len(rows)} fresh jobs before any 'apply today' alert...")
    else:
        waiting = _waiting_uids(db)
        rows = [r for r in db.jobs("status='shortlisted' AND assessment_json IS NULL", order="score DESC",
                                   limit=limit + len(waiting)) if r["uid"] not in waiting][:limit]
        if rows and not batch:
            say(f"Claude is assessing the top {len(rows)} shortlisted jobs...")
    if batch and rows:
        return submit_batch(db, ctx, llm, rows, say)
    n = 0
    from . import fulltext

    got = {"tried": 0, "found": 0}

    def one(r):
        job = db.row_to_job(r)
        if not job.extra.get("full_text_tried") and len(job.description or "") < fulltext.SHORT:
            text = fulltext.fetch(job)
            job.extra["full_text_tried"] = True
            got["tried"] += 1
            if text:
                job.description = text
                got["found"] += 1
        return r, job, assess(llm, ctx, job, r["sponsor_match"])

    with cf.ThreadPoolExecutor(4) as ex:
        for fut in cf.as_completed([ex.submit(one, r) for r in rows]):
            try:
                r, job, a = fut.result()
                # SQLite is written from this thread only
                db.conn.execute("UPDATE jobs SET description=?, extra=? WHERE uid=?",
                                (job.description, json.dumps(job.extra), r["uid"]))
                from .prompts import ASSESS_RULES
                db.set_assessment(r["uid"], a.fit_score, json.dumps({**a.model_dump(), "rules": ASSESS_RULES}))
                if a.verdict == "skip":
                    db.conn.execute("UPDATE jobs SET status='skipped' WHERE uid=?", (r["uid"],))
                n += 1
            except BudgetReached as e:
                if not got.get("budget"):
                    got["budget"] = 1
                    say(f"  {e}. The rest are assessed tomorrow.")
            except LLMError as e:
                say(f"  assessment failed: {e}")
    db.commit()
    if got["tried"]:
        say(f"  Full advert text found for {got['found']} of {got['tried']} short adverts.")
    return n


def _with_full_text(db: DB, r) -> Job:
    from . import fulltext
    job = db.row_to_job(r)
    if not job.extra.get("full_text_tried") and len(job.description or "") < fulltext.SHORT:
        text = fulltext.fetch(job)
        job.extra["full_text_tried"] = True
        if text:
            job.description = text
        db.conn.execute("UPDATE jobs SET description=?, extra=? WHERE uid=?",
                        (job.description, json.dumps(job.extra), r["uid"]))
    return job


def submit_batch(db: DB, ctx: Context, llm: LLM, rows: list, say: Callable[[str], None] = print) -> int:
    """Send assessments as one Message Batch at half price. harvest_batches() stores the results."""
    from .assess import request
    from .llm import BudgetReached
    items, mapping = [], {}
    for i, r in enumerate(rows):
        job = _with_full_text(db, r)
        system, prompt = request(ctx, job, r["sponsor_match"])
        cid = f"j{i}"
        items.append((cid, system, prompt))
        mapping[cid] = r["uid"]
    db.commit()
    lc = ctx.settings["llm"]
    model = lc.get("assess_model") or lc["model"]
    try:
        batch_id = llm.batch_submit(items, FitAssessment, effort=lc["assess_effort"], model=model)
    except BudgetReached as e:
        say(f"  {e}. Assessments wait for tomorrow.")
        return 0
    except LLMError as e:
        say(f"  Batch failed ({e}); assessing one by one instead.")
        return assess_top(db, ctx, llm, uids=[r["uid"] for r in rows], say=say)
    pending = _pending_batches(db) + [{"id": batch_id, "map": mapping, "model": model,
                                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}]
    db.set_learned("assess_batches", pending)
    db.commit()
    say(f"Sent {len(rows)} jobs to Claude as a batch (half price). Results usually take a few minutes.")
    return len(rows)


def harvest_batches(db: DB, ctx: Context, llm: Optional[LLM], say: Callable[[str], None] = print) -> int:
    """Store the results of finished assessment batches. Returns how many jobs got an assessment."""
    if not llm:
        return 0
    from .prompts import ASSESS_RULES
    pending, keep, stored = _pending_batches(db), [], 0
    for b in pending:
        try:
            if llm.batch_status(b["id"]) != "ended":
                keep.append(b)
                continue
            results = llm.batch_results(b["id"], FitAssessment, model=b.get("model"))
        except Exception as e:
            log.debug("batch %s check failed: %s", b["id"], e)
            age = datetime.now(timezone.utc) - datetime.fromisoformat(b["at"])
            if age < timedelta(days=2):          # try again later; give up on very old ones
                keep.append(b)
            continue
        failed = 0
        for cid, a, err in results:
            uid = b["map"].get(cid)
            row = db.get_job(uid) if uid else None
            if not row or row["assessment_json"]:
                continue
            if a is None:
                failed += 1                      # it stays unassessed and is picked again next time
                continue
            db.set_assessment(uid, a.fit_score, json.dumps({**a.model_dump(), "rules": ASSESS_RULES}))
            if a.verdict == "skip" and row["status"] == "shortlisted":
                db.conn.execute("UPDATE jobs SET status='skipped' WHERE uid=?", (uid,))
            stored += 1
        if failed:
            say(f"  {failed} assessments in a batch didn't come back; they'll be tried again.")
    db.set_learned("assess_batches", keep)
    db.commit()
    if stored:
        say(f"Stored {stored} assessments from Claude's batch.")
    return stored


def wait_for_batches(db: DB, ctx: Context, llm: Optional[LLM], minutes: float, say: Callable[[str], None] = print,
                     poll_seconds: float = 30) -> int:
    """Wait (up to `minutes`) for pending batches, storing results as they finish."""
    import time
    deadline, stored = time.monotonic() + minutes * 60, 0
    if _pending_batches(db) and minutes > 0:
        say(f"Waiting for Claude's batch (up to {minutes:g} minutes; set llm.batch_wait_minutes to change)...")
    while _pending_batches(db) and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        stored += harvest_batches(db, ctx, llm, say)
    if _pending_batches(db):
        say("  The batch is still running; the next quick check (11:30, 15:30 or 19:30) picks up the results.")
    return stored


def prepared_today(db: DB) -> int:
    return int(db.get_learned(f"prepared:{datetime.now().date().isoformat()}", 0) or 0)


def _count_prepared(db: DB, n: int = 1) -> None:
    db.set_learned(f"prepared:{datetime.now().date().isoformat()}", prepared_today(db) + n)


def apply_best(db: DB, ctx: Context, llm: Optional[LLM], mode: str, max_apply: int, st: "RunStats",
               say: Callable[[str], None] = print) -> list:
    """Build packs (and apply, in auto/review mode) for the best assessed jobs, within today's allowance."""
    thr = ctx.settings["scoring"]["apply_threshold"]
    room = max(0, max_apply - prepared_today(db))
    where = "status='shortlisted' AND fit_score >= ?" if llm else "status='shortlisted' AND score >= ?"
    best = db.jobs(where, (thr,), order="COALESCE(fit_score, score) DESC", limit=room) if room else []
    if mode == "none" or not best:
        return best
    from .apply import prepare_and_apply
    for r in best:
        if llm and llm.over_budget():
            say(f"Today's Claude budget (${llm.budget_usd:.2f}) is used up: the other matches wait for tomorrow.")
            break
        say(f"Preparing {r['title']} at {r['company']}...")
        try:
            out = prepare_and_apply(db, ctx, llm, r["uid"], mode=mode)
            st.packed += 1
            st.applied += int(out.submitted)
            _count_prepared(db)
            db.commit()
            for m in out.messages[-3:]:
                say(f"  {m}")
        except Exception as e:
            st.errors.append(f"apply failed for {r['company']}: {e}")
    return best


def watch(db: DB, ctx: Context, llm: Optional[LLM], say: Callable[[str], None] = print) -> list:
    """Quick check for new jobs; pushes "apply today" alerts for the excellent ones."""
    from . import alerts

    register = load_register(ctx)
    # assessments from the morning's batch that finished after the daily run stopped waiting
    if harvest_batches(db, ctx, llm, say):
        mode = db.get_learned("daily_mode") or ctx.settings["apply"]["mode"]
        apply_best(db, ctx, llm, mode, ctx.settings["apply"]["max_applications_per_day"], RunStats(), say)
    st = collect(db, ctx, register, say)
    score_all(db, ctx, register)
    if llm and st.new:
        assess_top(db, ctx, llm, limit=ctx.settings["alerts"]["max_assess_per_watch"], say=say, fresh_only=True)
    hot = alerts.send(db, ctx, say, require_fit=llm is not None)
    say(f"{st.new} new jobs, {len(hot)} worth applying to today.")
    from . import health
    for i in health.insights(db):
        if i.priority == 1 and db.get_learned(f"health_alerted:{i.title}") != datetime.now(timezone.utc).date().isoformat():
            say(f"  ! {i.title}: {i.detail}")
            notify.push(f"JobStream: {i.title}", i.detail)
            db.set_learned(f"health_alerted:{i.title}", datetime.now(timezone.utc).date().isoformat())
    db.log("watch", f"new={st.new} hot={len(hot)}")
    _refresh_dashboard(db, ctx)
    return hot


def _refresh_dashboard(db: DB, ctx: Context) -> None:
    try:
        from . import dashboard
        dashboard.build(db, ctx)
    except Exception as e:
        log.debug("dashboard build failed: %s", e)


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
        db.set_learned("visa_routes", [{"name": r.name, "status": r.status, "summary": r.summary, "link": r.link}
                                       for r in routes])
    except Exception as e:
        log.debug("visa route check failed: %s", e)

    # 2) learn from results so far, then search and score
    if ctx.settings["scoring"].get("adaptive", True):
        learn.learn_weights(db)
    harvest_batches(db, ctx, llm, say)          # results of earlier batches that finished late
    st = collect(db, ctx, register, say)
    st.shortlisted = score_all(db, ctx, register)
    say(f"{st.shortlisted} jobs on the shortlist.")
    lc = ctx.settings["llm"]
    if lc.get("batch_assessments", True):
        st.assessed = assess_top(db, ctx, llm, say=say, batch=True)
        if st.assessed:
            wait_for_batches(db, ctx, llm, float(lc.get("batch_wait_minutes", 20)), say)
    else:
        st.assessed = assess_top(db, ctx, llm, say=say)

    # prepare packs (and apply, if asked) for the best ones
    mode = apply_mode or ctx.settings["apply"]["mode"]
    db.set_learned("daily_mode", mode)        # the quick checks use it for results that arrive later
    max_apply = max_apply if max_apply is not None else ctx.settings["apply"]["max_applications_per_day"]
    thr = ctx.settings["scoring"]["apply_threshold"]
    best = apply_best(db, ctx, llm, mode, max_apply, st, say)
    if not best and mode != "none" and not _pending_batches(db):
        top = db.conn.execute("SELECT title, company, fit_score FROM jobs WHERE status='shortlisted' AND fit_score IS NOT NULL "
                              "ORDER BY fit_score DESC LIMIT 1").fetchone() if llm else None
        if top:
            say(f"No job reached a Claude fit of {thr}, so no packs were built. Best so far: {top['fit_score']:.0f} for "
                f"{top['title']} at {top['company']}. See every verdict and the reasons with `jobstream list --assessed`; build one anyway with "
                f"`jobstream apply <id> --mode pack`, or lower scoring.apply_threshold in config/settings.yaml.")

    # fresh, excellent jobs: push "apply today" (Claude checks them first when it's configured)
    from . import alerts
    if llm:
        assess_top(db, ctx, llm, limit=ctx.settings["alerts"]["max_assess_per_watch"], say=say, fresh_only=True)
    for r in alerts.send(db, ctx, say, require_fit=llm is not None):
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
                                                  f"Email: \"{u.subject}\". Check it, then run `jobstream status <id> offer`."))
                elif u.verdict == "interview":
                    extra_insights.append(Insight(1, f"Interview invitation: {u.company}",
                                                  f"{u.title}. Your prep pack is in the application folder (interview-prep.md)."))
                elif u.verdict == "rejected" and u.applied:
                    st.errors.append(f"Inbox: {u.company} ({u.title}) said no. Marked rejected.")
        except Exception as e:
            st.errors.append(f"Inbox check failed: {e}")

    from . import health
    extra_insights += health.insights(db)
    ins = extra_insights + insights.compute(db, ctx)
    ins.sort(key=lambda i: i.priority)
    notes = st.errors[:10]
    if llm:
        notes.append(f"Claude usage this run: {llm.usage_summary()}")
        say(f"Claude: {llm.usage_summary()}")
    md, path = digest.build(db, ctx, ins, st.new, notes)
    say(f"Digest written to {path}")
    top_titles = [f"{r['company']}: {r['title']}" for r in best[:3]]
    if st.new or ins:
        notify.push(f"JobStream: {st.new} new, {st.packed} ready, {st.applied} applied",
                    ("\n".join(top_titles) + "\n\n" + "\n".join(f"- {i.title}" for i in ins[:4])).strip())
        notify.email(f"JobStream digest: {st.new} new jobs, {st.packed} applications ready", md, digest.to_html(md))
    db.log("run", f"fetched={st.fetched} new={st.new} short={st.shortlisted} assessed={st.assessed} "
                  f"packed={st.packed} applied={st.applied}")
    _refresh_dashboard(db, ctx)
    return st
