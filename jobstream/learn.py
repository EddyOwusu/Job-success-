"""Learn from your own results: which kinds of applications get replies and interviews.

Every application stores a snapshot of what we knew when you applied (sector,
source, scores, how fresh the advert was, whether Claude wrote the CV...). When
outcomes come in (interview, rejection, silence), `report()` shows what is
working, and `learn_weights()` nudges the scoring weights towards the parts of
the score that actually predict interviews for you.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import DB
from .matching import WEIGHTS

POSITIVE = {"interview", "offer"}
NEGATIVE = {"rejected"}
GHOST_DAYS = 21          # no news after this long counts as a "no"
MIN_GROUP = 5            # smaller groups are reported as "too few to tell"
MIN_DECIDED = 20         # applications with a known result before weights change
MIN_POSITIVE = 3


def snapshot(job_row, *, method: str, claude: bool, statement: bool = False) -> dict:
    """What we knew about the job when you applied."""
    extra = json.loads(job_row["extra"] or "{}")
    score = json.loads(job_row["score_json"] or "{}")
    assessment = json.loads(job_row["assessment_json"] or "{}") if job_row["assessment_json"] else {}
    days_old = None
    if job_row["posted_at"]:
        try:
            posted = datetime.fromisoformat(job_row["posted_at"])
            posted = posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)
            days_old = max(0, (datetime.now(timezone.utc) - posted).days)
        except ValueError:
            pass
    return {
        "sector": extra.get("sector") or "tech",
        "source": job_row["source"],
        "method": method,
        "claude": claude,
        "statement": statement,
        "score": job_row["score"],
        "fit": job_row["fit_score"],
        "verdict": assessment.get("verdict"),
        "components": {k: score.get(k) for k in WEIGHTS},
        "days_old": days_old,
        "salary_known": bool(job_row["salary_min"] or job_row["salary_max"]),
        "on_register": bool(job_row["sponsor_match"]),
    }


@dataclass
class App:
    features: dict
    outcome: str        # positive | negative | ghosted | pending
    networked: bool


def _outcome(status: str, applied_at: str) -> str:
    if status in POSITIVE:
        return "positive"
    if status in NEGATIVE:
        return "negative"
    try:
        applied = datetime.fromisoformat(applied_at)
    except (TypeError, ValueError):
        return "pending"
    if datetime.now(timezone.utc) - applied > timedelta(days=GHOST_DAYS):
        return "ghosted"
    return "pending"


def load_apps(db: DB) -> list[App]:
    rows = db.conn.execute(
        """SELECT a.features, a.applied_at, j.status, a.job_uid,
                  (SELECT COUNT(*) FROM followups f WHERE f.job_uid=a.job_uid AND f.done=1) AS sent
           FROM applications a JOIN jobs j ON j.uid=a.job_uid"""
    ).fetchall()
    return [App(json.loads(r["features"] or "{}"), _outcome(r["status"], r["applied_at"]), r["sent"] > 0) for r in rows]


# ---------------------------------------------------------------------------- report
@dataclass
class Group:
    label: str
    n: int
    decided: int
    positive: int

    @property
    def rate(self) -> Optional[float]:
        return self.positive / self.decided if self.decided >= MIN_GROUP else None


@dataclass
class Report:
    total: int = 0
    pending: int = 0
    positive: int = 0
    negative: int = 0
    ghosted: int = 0
    breakdowns: dict[str, list[Group]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)

    @property
    def decided(self) -> int:
        return self.positive + self.negative + self.ghosted

    @property
    def interview_rate(self) -> Optional[float]:
        return self.positive / self.decided if self.decided else None


def _band(v, edges: list[tuple[float, str]], none_label="unknown") -> str:
    if v is None:
        return none_label
    for edge, label in edges:
        if v < edge:
            return label
    return edges[-1][1]


DIMENSIONS = {
    "Sector": lambda f, a: (f.get("sector") or "tech").upper(),
    "Source": lambda f, a: f.get("source") or "?",
    "Keyword score": lambda f, a: _band(f.get("score"), [(60, "under 60"), (70, "60-69"), (80, "70-79"), (999, "80+")]),
    "Claude fit": lambda f, a: _band(f.get("fit"), [(60, "under 60"), (70, "60-69"), (80, "70-79"), (999, "80+")], "not assessed"),
    "Advert age when applied": lambda f, a: _band(f.get("days_old"), [(3, "0-2 days"), (8, "3-7 days"), (15, "8-14 days"), (9999, "15+ days")]),
    "CV written by": lambda f, a: "Claude" if f.get("claude") else "keyword tailoring",
    "Networking messages sent": lambda f, a: "yes" if a.networked else "no",
    "Salary in advert": lambda f, a: "stated" if f.get("salary_known") else "hidden",
}


def report(db: DB) -> Report:
    apps = load_apps(db)
    rep = Report(total=len(apps))
    for a in apps:
        setattr(rep, a.outcome, getattr(rep, a.outcome) + 1)
    for dim, fn in DIMENSIONS.items():
        groups: dict[str, Group] = {}
        for a in apps:
            label = fn(a.features, a)
            g = groups.setdefault(label, Group(label, 0, 0, 0))
            g.n += 1
            if a.outcome != "pending":
                g.decided += 1
                g.positive += a.outcome == "positive"
        rep.breakdowns[dim] = sorted(groups.values(), key=lambda g: -g.n)
    rep.findings = findings(rep)
    return rep


def findings(rep: Report) -> list[str]:
    """Plain-English conclusions, only where the numbers support one."""
    out: list[str] = []
    overall = rep.interview_rate
    if rep.decided < 10:
        out.append(f"{rep.decided} applications have a result so far. Patterns become reliable from about 20.")
        return out
    out.append(f"Overall: {rep.positive} interviews from {rep.decided} decided applications ({overall:.0%}).")
    for dim, groups in rep.breakdowns.items():
        rated = [g for g in groups if g.rate is not None]
        if len(rated) < 2:
            continue
        best = max(rated, key=lambda g: g.rate)
        worst = min(rated, key=lambda g: g.rate)
        if best.rate - worst.rate >= 0.15 and best.positive >= 2:
            out.append(f"{dim}: '{best.label}' gets interviews {best.rate:.0%} of the time "
                       f"vs {worst.rate:.0%} for '{worst.label}' ({best.decided} and {worst.decided} applications).")
    if overall is not None and overall < 0.05 and rep.decided >= 20:
        out.append("Under 5% of applications lead to interviews. Apply to fewer, higher-fit roles, send every "
                   "networking message, and get your master CV reviewed by someone in the industry.")
    return out


# ---------------------------------------------------------------------------- weights
def learn_weights(db: DB, save: bool = True) -> tuple[dict[str, float], list[str]]:
    """Shift scoring weights towards the score components that predict interviews.

    Compares the average value of each component for applications that led to an
    interview against those that didn't. Changes are capped at 0.6x-1.5x of the
    defaults and need at least 20 decided applications, 3 of them interviews.
    """
    apps = [a for a in load_apps(db) if a.outcome != "pending" and a.features.get("components")]
    pos = [a for a in apps if a.outcome == "positive"]
    neg = [a for a in apps if a.outcome != "positive"]
    if len(apps) < MIN_DECIDED or len(pos) < MIN_POSITIVE:
        return dict(WEIGHTS), [f"Need {MIN_DECIDED} decided applications with {MIN_POSITIVE}+ interviews to tune "
                               f"scoring (have {len(apps)} and {len(pos)})."]

    def mean(group, k):
        vals = [a.features["components"].get(k) for a in group if a.features["components"].get(k) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    raw = {}
    notes = []
    for k, w in WEIGHTS.items():
        diff = mean(pos, k) - mean(neg, k)          # components are 0-1
        mult = min(1.5, max(0.6, 1 + 1.5 * diff))
        raw[k] = w * mult
        if abs(mult - 1) >= 0.1:
            notes.append(f"{k}: {'more' if mult > 1 else 'less'} weight ({w} -> ~{w * mult:.0f}) because it "
                         f"{'predicts' if mult > 1 else 'does not predict'} your interviews")
    scale = 100 / sum(raw.values())
    weights = {k: round(v * scale, 1) for k, v in raw.items()}
    if save:
        db.set_learned("weights", weights)
    return weights, notes or ["Your results match the default weights; nothing changed."]


def current_weights(db: DB, settings: dict) -> dict[str, float]:
    if not settings.get("scoring", {}).get("adaptive", True):
        return dict(WEIGHTS)
    return db.get_learned("weights") or dict(WEIGHTS)


def report_markdown(rep: Report, weight_notes: list[str]) -> str:
    out = ["# What's working", "",
           f"{rep.total} applications: {rep.positive} interviews or offers, {rep.negative} rejections, "
           f"{rep.ghosted} no reply after {GHOST_DAYS} days, {rep.pending} still waiting.", ""]
    out += ["## Findings", ""] + [f"- {f}" for f in rep.findings] + [""]
    for dim, groups in rep.breakdowns.items():
        if not groups:
            continue
        out += [f"## {dim}", "", "| | Applications | With a result | Interviews | Interview rate |", "|---|---|---|---|---|"]
        for g in groups:
            rate = f"{g.rate:.0%}" if g.rate is not None else "too few to tell"
            out.append(f"| {g.label} | {g.n} | {g.decided} | {g.positive} | {rate} |")
        out.append("")
    out += ["## Scoring", ""] + [f"- {n}" for n in weight_notes]
    return "\n".join(out) + "\n"
