"""Source health: notice when a job source silently stops working.

Job sites change their pages and APIs without warning. A broken source doesn't
crash anything: it just returns nothing, and you'd never know you were missing
jobs. So every run records what each source returned, and this module compares
the latest run with the ones before it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from .db import DB, now_iso
from .insights import Insight

SOURCE_NAMES = {
    "greenhouse": "Greenhouse company boards", "lever": "Lever company boards", "ashby": "Ashby company boards",
    "smartrecruiters": "SmartRecruiters company boards", "workday": "Workday career sites",
    "nhs": "NHS Jobs", "jobsacuk": "jobs.ac.uk (universities)", "reed": "Reed", "adzuna": "Adzuna",
}
BOARD_KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
HISTORY = 6      # runs looked at


def new_run() -> str:
    return now_iso()


def record(db: DB, run_at: str, kind: str, key: str, seen: int, jobs: list, error: Optional[str]) -> None:
    empty = sum(1 for j in jobs if len(j.description or "") < 200)
    db.conn.execute("INSERT INTO source_runs (run_at, kind, key, seen, returned, empty_desc, error) VALUES (?,?,?,?,?,?,?)",
                    (run_at, kind, key, seen, len(jobs), empty, error))


@dataclass
class SourceStatus:
    kind: str
    name: str
    state: str = "ok"                  # ok | warn | broken | new
    detail: str = ""
    boards: int = 0
    seen: int = 0
    last_run: str = ""
    moved: list[str] = field(default_factory=list)   # boards that have returned nothing for several runs


def _runs(db: DB, kind: str) -> list[str]:
    return [r[0] for r in db.conn.execute(
        "SELECT DISTINCT run_at FROM source_runs WHERE kind=? ORDER BY run_at DESC LIMIT ?", (kind, HISTORY))]


def status(db: DB) -> list[SourceStatus]:
    out: list[SourceStatus] = []
    kinds = [r[0] for r in db.conn.execute("SELECT DISTINCT kind FROM source_runs")]
    for kind in sorted(kinds, key=lambda k: list(SOURCE_NAMES).index(k) if k in SOURCE_NAMES else 99):
        runs = _runs(db, kind)
        latest, earlier = runs[0], runs[1:]
        rows = db.conn.execute("SELECT * FROM source_runs WHERE kind=? AND run_at IN (%s)" % ",".join("?" * len(runs)),
                               (kind, *runs)).fetchall()
        by_run: dict[str, dict[str, object]] = {}
        for r in rows:
            by_run.setdefault(r["run_at"], {})[r["key"]] = r
        now = by_run[latest]
        st = SourceStatus(kind, SOURCE_NAMES.get(kind, kind), boards=len(now), last_run=latest,
                          seen=sum(r["seen"] or 0 for r in now.values()))
        if not earlier:
            st.state, st.detail = "new", "First run recorded; nothing to compare with yet."
            errs = [r for r in now.values() if r["error"]]
            if errs and len(errs) == len(now):
                st.state, st.detail = "broken", f"Failed: {errs[0]['error']}"
            out.append(st)
            continue

        if kind in BOARD_KINDS:
            dropped, moved = [], []
            for key, r in now.items():
                history = [by_run[run][key] for run in earlier if key in by_run[run]]
                had = [h for h in history if (h["seen"] or 0) > 0 and not h["error"]]
                if (r["error"] or (r["seen"] or 0) == 0) and history and (history[0]["seen"] or 0) > 0 and not history[0]["error"]:
                    dropped.append(key)
                if had and len(history) >= 2 and (r["seen"] or 0) == 0 and all((h["seen"] or 0) == 0 for h in history[:2]):
                    moved.append(key)
            st.moved = sorted(moved)
            if dropped and len(dropped) >= max(2, 0.4 * len(now)):
                st.state = "broken"
                st.detail = (f"{len(dropped)} of {len(now)} boards that worked last time returned nothing "
                             f"(e.g. {', '.join(sorted(dropped)[:3])}). The site's API has probably changed.")
            elif st.moved:
                st.state = "warn"
                st.detail = (f"{len(st.moved)} board(s) have returned nothing for 3 runs and may have moved to a "
                             f"different careers site: {', '.join(st.moved[:5])}.")
        else:
            r = now.get("")
            history = [by_run[run][""] for run in earlier if "" in by_run[run]]
            good = [h["seen"] for h in history if (h["seen"] or 0) > 0 and not h["error"]]
            if r is None:
                pass
            elif r["error"]:
                st.state, st.detail = "broken", f"Every search failed: {r['error']}"
            elif (r["seen"] or 0) == 0 and good:
                st.state = "broken"
                st.detail = (f"Returned no results at all; it usually returns about {int(median(good))}. "
                             f"The site's page or API has probably changed.")
            elif good and (r["seen"] or 0) < 0.25 * median(good):
                st.state = "warn"
                st.detail = f"Returned {r['seen']} results; it usually returns about {int(median(good))}."
        # adverts that came back without their text: the advert page layout changed
        returned = sum(r["returned"] or 0 for r in now.values())
        empty = sum(r["empty_desc"] or 0 for r in now.values())
        if st.state == "ok" and returned >= 5 and empty / returned > 0.5 and kind != "adzuna":
            st.state = "warn"
            st.detail = (f"{empty} of {returned} new adverts came back without their full text. "
                         f"The advert page layout may have changed, so scores for these are unreliable.")
        out.append(st)
    return out


def insights(db: DB) -> list[Insight]:
    out = []
    rows = status(db)
    if len(rows) >= 3 and all(s.state == "broken" for s in rows):
        return [Insight(2, "The last search couldn't reach any job site",
                        "Every source failed at once, which usually means the computer was offline. "
                        "It will try again on the next run.")]
    for s in rows:
        if s.state == "broken":
            out.append(Insight(1, f"{s.name} looks broken", s.detail + " You may be missing jobs from this source. "
                               "Run `jobagent health`, and check for an update to the agent."))
        elif s.state == "warn":
            out.append(Insight(3, f"Check {s.name}", s.detail))
    return out


def report(db: DB) -> str:
    rows = status(db)
    if not rows:
        return "No runs recorded yet. Run `jobagent search` first."
    mark = {"ok": "OK    ", "new": "NEW   ", "warn": "CHECK ", "broken": "BROKEN"}
    lines = [f"{'':7}{'source':<34}{'boards':>7}{'postings seen':>15}  last run"]
    for s in rows:
        boards = str(s.boards) if s.kind in BOARD_KINDS else "-"
        lines.append(f"{mark[s.state]} {s.name:<34}{boards:>7}{s.seen:>15,}  {s.last_run[:16].replace('T', ' ')}")
        if s.detail and s.state != "ok":
            lines.append(f"{'':7}{s.detail}")
    return "\n".join(lines)
