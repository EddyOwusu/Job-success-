"""The daily digest: best new jobs, why they fit, what to do next."""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from .config import OUTPUT_DIR, Context
from .db import DB
from .insights import Insight


def _job_line(r) -> str:
    b = json.loads(r["score_json"]) if r["score_json"] else {}
    a = json.loads(r["assessment_json"]) if r["assessment_json"] else None
    fit = f"fit {a['fit_score']} ({a['verdict']})" if a else "not assessed"
    sal = ""
    if r["salary_min"] or r["salary_max"]:
        sal = f" | £{int(r['salary_min'] or 0):,}-£{int(r['salary_max'] or 0):,}"
    sponsor = f"sponsor: {r['sponsor_match']}" if r["sponsor_match"] else "sponsor: not on register"
    sector = (json.loads(r["extra"] or "{}").get("sector") or "tech").upper()
    out = [f"- [{sector}] **{r['title']}** at **{r['company']}** ({r['location'][:60]}){sal}",
           f"  score {r['score']:.0f} | {fit} | {sponsor} | id `{r['uid']}`",
           f"  {r['url']}"]
    if b.get("matched_skills"):
        out.append(f"  matched: {', '.join(b['matched_skills'][:8])}")
    if a:
        if a.get("strengths"):
            out.append(f"  why: {a['strengths'][0]}")
        if a.get("red_flags"):
            out.append(f"  watch out: {a['red_flags'][0]}")
    return "\n".join(out)


def build(db: DB, ctx: Context, insights: list[Insight], new_count: int, run_notes: list[str]) -> tuple[str, Path]:
    thr = ctx.settings["scoring"]["shortlist_threshold"]
    top = db.jobs("status IN ('new','shortlisted','packed') AND score >= ? AND first_seen >= date('now','-2 day')",
                  (thr,), order="COALESCE(fit_score, score) DESC", limit=15)
    backlog = db.jobs("status IN ('new','shortlisted') AND score >= ?", (thr,),
                      order="COALESCE(fit_score, score) DESC", limit=10)
    counts = dict(db.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    lines = [f"# Job search digest, {date.today():%A %d %B %Y}", "",
             f"{new_count} new jobs found this run. Pipeline: " +
             ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), ""]
    if insights:
        lines += ["## Suggestions", ""]
        icon = {1: "[ACT]", 2: "[THIS WEEK]", 3: "[FYI]"}
        lines += [f"- {icon[i.priority]} **{i.title}**: {i.detail}" for i in insights]
        lines.append("")
    lines += ["## Best new matches", ""]
    lines += [_job_line(r) for r in top] or ["No new jobs above your threshold today."]
    if backlog:
        lines += ["", "## Still waiting for you", ""] + [_job_line(r) for r in backlog]
    due = db.due_followups()
    if due:
        lines += ["", "## Follow-ups due", ""] + [f"- {d['company']}: {d['title']} ({d['kind']}): {d['message']}" for d in due]
    if run_notes:
        lines += ["", "## Run notes", ""] + [f"- {n}" for n in run_notes]
    md = "\n".join(lines) + "\n"
    path = OUTPUT_DIR / "digests" / f"digest-{date.today():%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return md, path


def to_html(md: str) -> str:
    """Tiny Markdown-to-HTML for the email version."""
    import re

    out = []
    for line in md.splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"`(.+?)`", r"<code>\1</code>", esc)
        esc = re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', esc)
        if line.startswith("# "):
            out.append(f"<h1>{esc[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("- "):
            out.append(f"<p style='margin:10px 0 0'>{esc[2:]}</p>")
        elif line.startswith("  "):
            out.append(f"<div style='margin-left:16px;color:#444'>{esc.strip()}</div>")
        elif line:
            out.append(f"<p>{esc}</p>")
    return "<html><body style='font-family:sans-serif;max-width:760px'>" + "\n".join(out) + "</body></html>"
