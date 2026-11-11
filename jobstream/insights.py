"""Suggestions the agent announces: skill gaps, better titles, hot companies, overdue follow-ups..."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Context
from .db import DB
from .matching import _title_tokens


@dataclass
class Insight:
    priority: int      # 1 = act today, 2 = this week, 3 = good to know
    title: str
    detail: str


def _floor(ctx: Context) -> int:
    from .visa import threshold_for
    return threshold_for(ctx.profile.visa, ctx.settings)[0]


def compute(db: DB, ctx: Context) -> list[Insight]:
    out: list[Insight] = []
    thr = ctx.settings["scoring"]["shortlist_threshold"]
    rows = db.jobs("score_json IS NOT NULL", limit=5000)
    breakdowns = [(r, json.loads(r["score_json"])) for r in rows]
    viable = [(r, b) for r, b in breakdowns if not b["blockers"]]

    # ---- follow-ups due
    due = db.due_followups()
    if due:
        lines = "; ".join(f"{d['company']} ({d['kind']}, due {d['due']})" for d in due[:8])
        out.append(Insight(1, f"{len(due)} follow-up(s) due", f"{lines}. Run `jobstream followups`."))

    # ---- strong new matches waiting
    waiting = [r for r in rows if r["status"] in ("new", "shortlisted") and (r["fit_score"] or 0) >= ctx.settings["scoring"]["apply_threshold"]]
    if waiting:
        names = ", ".join(f"{r['company']} ({r['title'][:40]})" for r in waiting[:5])
        out.append(Insight(1, f"{len(waiting)} strong matches ready to apply", f"{names}. Run `jobstream apply --top 5`."))

    # ---- skill gaps, and the projects that close them
    try:
        from . import growth
        active = growth.active(db)
        for pr in active:
            started = pr["created_at"][:10]
            out.append(Insight(3, f"Project in progress: {pr['skill']}",
                               f"Planned on {started}. The plan is in {pr['plan_path']}. When it's built, run "
                               f"`jobstream grow --done \"{pr['skill']}\"`."))
        gap_list, pool = growth.gaps(db, ctx, limit=4)
        fresh = [g for g in gap_list if not g.status]
        if fresh and not active:
            top = fresh[0]
            detail = ", ".join(f"{g.skill} ({g.share:.0%})" for g in fresh)
            unlock = f" {top.unlocks} near-miss jobs would reach your shortlist with it." if top.unlocks else ""
            out.append(Insight(2, f"{top.skill} would open the most doors",
                               f"Missing from your profile, across {pool} jobs you nearly match: {detail}. "
                               f"{top.skill} is asked for by {', '.join(top.employers[:4])}.{unlock} Get a two-week "
                               f"project plan with `jobstream grow --plan`. If you already have one of these, add "
                               f"it to config/profile.yaml instead."))
    except Exception:
        pass

    # ---- titles you are not targeting but match
    targets = [_title_tokens(t) for t in ctx.profile.targets.roles]
    unseen = Counter()
    for r, b in viable:
        if b["skills"] >= 0.55 and b["title"] < 0.5:
            tt = frozenset(_title_tokens(r["title"]))
            if tt and not any(tt & t for t in targets):
                unseen[" ".join(sorted(tt))] += 1
    sugg = [(t, c) for t, c in unseen.most_common(3) if c >= 3]
    if sugg:
        out.append(Insight(2, "Job titles worth adding to your targets",
                           ", ".join(f"'{t}' ({c} jobs fit your skills)" for t, c in sugg)
                           + ". Add the ones you'd do to targets.roles."))

    # ---- companies with several openings
    by_co = Counter(r["company"] for r, b in viable if b["total"] >= thr)
    hot = [(c, n) for c, n in by_co.most_common(5) if n >= 3]
    if hot:
        out.append(Insight(2, "Companies hiring a lot for your profile",
                           ", ".join(f"{c} ({n} roles)" for c, n in hot)
                           + ". Network here first: one referral can cover several roles."))

    # ---- speculative approaches
    try:
        from . import speculative
        for r in speculative.due_followups(db):
            out.append(Insight(1, f"Follow up your note to {r['company']}",
                               f"Sent 7+ days ago with no reply recorded. The follow-up text is in "
                               f"{r['pack_dir']}/approach.md. Then run `jobstream speculative --close \"{r['company']}\"` "
                               f"or `--replied`."))
        waiting = speculative.unsent(db)
        if waiting:
            out.append(Insight(2, f"{len(waiting)} speculative approaches drafted but not sent",
                               ", ".join(r["company"] for r in waiting[:5])
                               + ". Send them, then run `jobstream speculative --sent \"<company>\"`."))
        elif speculative.weekly_room(db, ctx) == ctx.settings["speculative"]["max_per_week"] and len(viable) >= 20:
            out.append(Insight(3, "Try a few speculative approaches this week",
                               "Some licensed sponsors use your stack but have no vacancy at your level. "
                               "See them with `jobstream speculative`."))
    except Exception:
        pass

    # ---- Scale-up sponsors
    su = [(r, b) for r, b in viable if b.get("scaleup") and r["status"] in ("new", "shortlisted", "packed")]
    if su:
        names = ", ".join(dict.fromkeys(r["company"] for r, _ in sorted(su, key=lambda x: -x[1]["total"])[:6]))
        out.append(Insight(2, f"{len(su)} open jobs at Scale-up sponsors",
                           f"{names}. On the Scale-up visa you're tied to the sponsor for only 6 months, then you can "
                           f"move freely. See them with `jobstream list --scaleup`."))

    # ---- salary / visa
    sponsor_ok = [b for _, b in breakdowns if b["sponsorship"] > 0]
    blocked_salary = sum(1 for _, b in breakdowns if any("threshold" in x for x in b["blockers"]))
    if blocked_salary >= 5:
        out.append(Insight(3, f"{blocked_salary} jobs pay below the Skilled Worker threshold",
                           "Target more senior titles or larger employers, or check whether you qualify for "
                           "the new-entrant rate (set visa.new_entrant: true if you do)."))
    unknown = sum(1 for _, b in viable if b["salary"] == 0.5)
    if viable and unknown / len(viable) > 0.5:
        out.append(Insight(3, "Most adverts hide the salary",
                           "Ask the recruiter early: 'Is the role able to meet the Skilled Worker salary "
                           f"threshold of £{_floor(ctx):,}?' It saves weeks."))

    # ---- funnel health
    apps = db.conn.execute("SELECT status, applied_at FROM applications").fetchall()
    n_apps = len(apps)
    interviews = db.conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('interview','offer')").fetchone()[0]
    if n_apps >= 15 and interviews == 0:
        out.append(Insight(1, f"{n_apps} applications, no interviews yet",
                           "Change something: apply to fewer, better-fit roles (fit 75+), send every networking "
                           "message, and ask someone in the industry to review your master CV."))
    stale_cut = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    stale = db.conn.execute("SELECT COUNT(*) FROM jobs j JOIN applications a ON a.job_uid=j.uid "
                            "WHERE j.status='applied' AND a.applied_at < ?", (stale_cut,)).fetchone()[0]
    if stale:
        out.append(Insight(3, f"{stale} applications with no news for 3+ weeks",
                           "Send one last polite nudge, then mark them with `jobstream status <id> rejected` and move on."))
    if not sponsor_ok and rows:
        out.append(Insight(1, "No jobs at licensed sponsors yet",
                           "Run `jobstream discover` to find more sponsor job boards, and add dream companies to data/seed_companies.yaml."))
    if ctx.using_examples:
        out.insert(0, Insight(1, "You are using the example profile",
                              "Copy config/profile.example.yaml and config/cv_master.example.yaml to profile.yaml / "
                              "cv_master.yaml and fill in your real details (`jobstream init`)."))
    return sorted(out, key=lambda i: i.priority)
