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
        out.append(Insight(1, f"{len(due)} follow-up(s) due", f"{lines}. Run `jobagent followups`."))

    # ---- strong new matches waiting
    waiting = [r for r in rows if r["status"] in ("new", "shortlisted") and (r["fit_score"] or 0) >= ctx.settings["scoring"]["apply_threshold"]]
    if waiting:
        names = ", ".join(f"{r['company']} ({r['title'][:40]})" for r in waiting[:5])
        out.append(Insight(1, f"{len(waiting)} strong matches ready to apply", f"{names}. Run `jobagent apply --top 5`."))

    # ---- skill gaps in good-fit jobs
    good = [b for _, b in viable if b["total"] >= thr - 10]
    if len(good) >= 5:
        gaps = Counter(s for b in good for s in b["missing_skills"][:6])
        top = [(s, c) for s, c in gaps.most_common(5) if c / len(good) >= 0.2]
        if top:
            detail = ", ".join(f"{s} ({c / len(good):.0%} of jobs)" for s, c in top)
            out.append(Insight(2, "Skills that would open more doors",
                               f"Your best-matching jobs often ask for: {detail}. A small public project or "
                               f"certification in the top one would raise your scores. If you already have "
                               f"any of these, add them to config/profile.yaml."))

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
                           f"threshold of £{ctx.settings['sponsorship']['general_threshold_gbp']:,}?' It saves weeks."))

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
                           "Send one last polite nudge, then mark them with `jobagent status <id> rejected` and move on."))
    if not sponsor_ok and rows:
        out.append(Insight(1, "No jobs at licensed sponsors yet",
                           "Run `jobagent discover` to find more sponsor job boards, and add dream companies to data/seed_companies.yaml."))
    if ctx.using_examples:
        out.insert(0, Insight(1, "You are using the example profile",
                              "Copy config/profile.example.yaml and config/cv_master.example.yaml to profile.yaml / "
                              "cv_master.yaml and fill in your real details (`jobagent init`)."))
    return sorted(out, key=lambda i: i.priority)
