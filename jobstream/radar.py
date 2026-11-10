"""Sponsor radar: spot companies that have just been licensed to sponsor visas.

The Home Office republishes the sponsor register every working day. We keep every
name we have seen, so each new download shows:
  - new sponsors: a fresh licence usually means the company plans to hire from
    abroad soon, often before the jobs are advertised widely
  - removed sponsors: a licence that disappeared (revoked, surrendered or expired)
  - downgraded sponsors: an A rating that became B, which signals compliance problems
New tech-looking sponsors are checked for public job boards and added to your search.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .db import DB
from .discovery import priority, probe_company
from .sponsors import Sponsor, SponsorRegister, core_name


@dataclass
class RadarReport:
    first_run: bool = False
    new: list[Sponsor] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    downgraded: list[str] = field(default_factory=list)
    boards_found: list[tuple[str, str, str, int]] = field(default_factory=list)   # (company, ats, token, uk jobs)
    pipeline_warnings: list[str] = field(default_factory=list)


def update(db: DB, register: SponsorRegister, today: date | None = None) -> RadarReport:
    """Compare this register with what we've seen before. Safe to call more than once a day."""
    today_s = (today or date.today()).isoformat()
    rep = RadarReport()
    seen = {r["name"]: r for r in db.conn.execute("SELECT name, rating, removed_at FROM sponsor_seen")}
    current = {}
    for sp in register.sponsors:
        current.setdefault(sp.name, sp)
    if not seen:
        rep.first_run = True
        db.conn.executemany(
            "INSERT OR IGNORE INTO sponsor_seen (name, town, rating, first_seen, last_seen, baseline) VALUES (?,?,?,?,?,1)",
            [(n, sp.town, sp.rating, today_s, today_s) for n, sp in current.items()])
        db.commit()
        return rep

    new_rows, back_rows, seen_rows, rating_rows = [], [], [], []
    for name, sp in current.items():
        old = seen.get(name)
        if old is None:
            new_rows.append((name, sp.town, sp.rating, today_s, today_s))
            rep.new.append(sp)
        else:
            if old["removed_at"]:
                back_rows.append((today_s, name))
            else:
                seen_rows.append((today_s, name))
            if old["rating"] and old["rating"] != sp.rating:
                rating_rows.append((old["rating"], sp.rating, today_s, name))
                if "A rating" in (old["rating"] or "") and "B rating" in sp.rating:
                    rep.downgraded.append(name)
    db.conn.executemany("INSERT INTO sponsor_seen (name, town, rating, first_seen, last_seen, baseline) "
                        "VALUES (?,?,?,?,?,0)", new_rows)
    db.conn.executemany("UPDATE sponsor_seen SET last_seen=?, removed_at=NULL WHERE name=?", back_rows)
    db.conn.executemany("UPDATE sponsor_seen SET last_seen=? WHERE name=?", seen_rows)
    db.conn.executemany("UPDATE sponsor_seen SET prev_rating=?, rating=?, rating_changed_at=? WHERE name=?", rating_rows)
    gone = [n for n, r in seen.items() if n not in current and not r["removed_at"]]
    db.conn.executemany("UPDATE sponsor_seen SET removed_at=? WHERE name=?", [(today_s, n) for n in gone])
    rep.removed = gone
    db.commit()
    rep.pipeline_warnings = pipeline_warnings(db, set(gone), set(rep.downgraded))
    return rep


def pipeline_warnings(db: DB, removed: set[str], downgraded: set[str]) -> list[str]:
    """Jobs you are pursuing at employers that just lost their licence or their A rating."""
    if not (removed or downgraded):
        return []
    out = []
    rows = db.conn.execute("SELECT company, title, sponsor_match, status FROM jobs "
                           "WHERE status IN ('shortlisted','packed','applied','interview','offer') AND sponsor_match IS NOT NULL")
    for r in rows:
        if r["sponsor_match"] in removed:
            out.append(f"{r['company']} ({r['title']}, {r['status']}): its sponsor licence is no longer on the register. "
                       f"Ask HR whether they can still sponsor before going further.")
        elif r["sponsor_match"] in downgraded:
            out.append(f"{r['company']} ({r['title']}, {r['status']}): its licence was downgraded to a B rating. "
                       f"B-rated sponsors can't issue new certificates until they fix their compliance plan. Ask about it.")
    return out


def recent_new(db: DB, days: int = 14) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in db.conn.execute(
        "SELECT name, town, rating, first_seen FROM sponsor_seen WHERE baseline=0 AND first_seen>=? "
        "ORDER BY first_seen DESC", (since,))]


def scan(db: DB, register: SponsorRegister, keywords: list[str], days: int = 14, max_probes: int = 40,
         progress=None) -> RadarReport:
    """Probe recently licensed, tech-looking sponsors for job boards and add them to your search."""
    import re

    rep = RadarReport()
    by_name = {sp.name: sp for sp in register.sponsors}
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.I)
    fresh = [by_name[r["name"]] for r in recent_new(db, days) if r["name"] in by_name]
    rep.new = fresh
    # tech-looking names first, then everything else, most promising first
    candidates = sorted(fresh, key=lambda sp: (bool(pat.search(sp.name)), priority(sp)), reverse=True)
    todo = [sp for sp in candidates if not db.probed(sp.name)][:max_probes]
    for i, sp in enumerate(todo, 1):
        try:
            hits = probe_company(sp.name)
        except Exception:
            hits = []
        display = re.sub(r"\b(ltd|limited|plc|llp)\b\.?", "", sp.name, flags=re.I).strip(" ,.")
        for ats, token, n in hits:
            taken = db.conn.execute("SELECT company FROM boards WHERE ats=? AND token=?", (ats, token)).fetchone()
            if taken and core_name(taken[0]) != core_name(display):
                continue
            db.upsert_board(ats, token, display, sp.name, "live", n)
            rep.boards_found.append((display, ats, token, n))
        db.mark_probed(sp.name, ",".join(f"{a}:{t}" for a, t, _ in hits))
        if progress:
            progress(i, len(todo), sp.name, hits)
    db.commit()
    return rep


def report_markdown(db: DB, rep: RadarReport, days: int) -> str:
    out = [f"# Sponsor radar (last {days} days)", ""]
    if rep.first_run:
        out += ["First run: today's register is now the baseline. From the next download (the register "
                "updates every working day) you'll see newly licensed sponsors here.", ""]
        return "\n".join(out)
    new = recent_new(db, days)
    out += [f"{len(new)} newly licensed Skilled Worker sponsors.", ""]
    if rep.boards_found:
        out += ["## New sponsors with job boards (added to your daily search)", ""]
        out += [f"- {c}: {a} `{t}` ({n} UK jobs)" for c, a, t, n in rep.boards_found] + [""]
    if rep.pipeline_warnings:
        out += ["## Check these", ""] + [f"- {w}" for w in rep.pipeline_warnings] + [""]
    if new:
        # most promising for tech jobs first
        new.sort(key=lambda r: priority(Sponsor(r["name"], r["town"] or "", "", r["rating"] or "", "")), reverse=True)
        out += ["## Newly licensed (likely tech employers first)", "", "| First seen | Organisation | Town | Rating |",
                "|---|---|---|---|"]
        out += [f"| {r['first_seen']} | {r['name']} | {r['town']} | {r['rating']} |" for r in new[:200]]
    return "\n".join(out) + "\n"
