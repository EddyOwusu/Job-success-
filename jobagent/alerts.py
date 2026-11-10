"""Speed alerts: tell you about excellent, freshly posted jobs while applying early still matters.

Recruiters often start screening within days, so the first 48 hours count. `jobagent watch`
is a quick search (a minute or two, because known adverts are skipped) that you schedule a
few times a day. When a new job clears the bar it pushes "Apply today" to your phone.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import notify
from .config import Context
from .db import DB, now_iso


def _hours_ago(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return None
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def find_hot(db: DB, ctx: Context, limit: int = 5) -> list:
    """Shortlisted jobs, not yet alerted, found and posted recently, with a high enough score."""
    a = ctx.settings["alerts"]
    since = (datetime.now(timezone.utc) - timedelta(hours=a["max_age_hours"])).isoformat()
    rows = db.conn.execute(
        """SELECT * FROM jobs WHERE status IN ('shortlisted','packed') AND alerted_at IS NULL AND first_seen >= ?
           AND ((fit_score IS NOT NULL AND fit_score >= ?) OR (fit_score IS NULL AND score >= ?))
           ORDER BY COALESCE(fit_score, score) DESC""",
        (since, a["hot_fit"], a["hot_score"]),
    ).fetchall()
    hot = []
    for r in rows:
        age = _hours_ago(r["posted_at"])
        if age is not None and age > a["max_age_hours"] * 1.5:
            continue          # we only just found it, but it has been up for days
        hot.append(r)
    return hot[:limit]


def describe(r) -> tuple[str, str]:
    score = f"fit {r['fit_score']:.0f}" if r["fit_score"] is not None else f"score {r['score']:.0f}"
    bits = [score]
    age = _hours_ago(r["posted_at"])
    if age is not None:
        bits.append(f"posted {age:.0f}h ago" if age < 48 else f"posted {age / 24:.0f} days ago")
    if r["salary_min"] or r["salary_max"]:
        bits.append(f"£{int(r['salary_min'] or r['salary_max']):,}-£{int(r['salary_max'] or r['salary_min']):,}")
    b = json.loads(r["score_json"] or "{}")
    bits.append("Scale-up sponsor" if b.get("scaleup") else "licensed sponsor" if r["sponsor_match"] else "check sponsorship")
    title = f"Apply today: {r['title']} at {r['company']}"
    body = " · ".join(bits) + f"\njobagent apply {r['uid']}"
    return title, body


def send(db: DB, ctx: Context, say=print) -> list:
    """Push an alert for each hot job (once per job). Returns the jobs alerted."""
    hot = find_hot(db, ctx, limit=ctx.settings["alerts"]["max_per_run"])
    for r in hot:
        title, body = describe(r)
        say(f"  HOT  {title}  ({body.splitlines()[0]})")
        notify.push(title, body, url=r["url"] or "")
        db.conn.execute("UPDATE jobs SET alerted_at=? WHERE uid=?", (now_iso(), r["uid"]))
    db.commit()
    return hot
