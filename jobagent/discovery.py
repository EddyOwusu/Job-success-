"""Find hidden job boards: probe companies on the sponsor register for public ATS boards.

Most sponsoring tech employers post jobs on Greenhouse, Lever or Ashby. Those
boards have public APIs keyed by a short company slug. We turn each sponsor's
name into likely slugs and check them. A hit is a career page full of jobs at a
company that is *already licensed to sponsor you*, and most of those jobs never
reach the big job boards.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re
from pathlib import Path

import yaml

from .db import DB
from .http import get_json
from .sources import ATS
from .sources.base import is_uk
from .sponsors import SponsorRegister, _tokens, core_name

log = logging.getLogger(__name__)


def load_seed(path: Path, db: DB) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    n = 0
    for c in data.get("companies", []):
        db.upsert_board(c["ats"], c["token"], c["name"], None, "live", -1)
        n += 1
    db.commit()
    return n


def slug_candidates(name: str) -> list[str]:
    toks = _tokens(name)
    core = core_name(name).split()
    cands = []
    for t in (core, toks):
        if t:
            cands += ["".join(t), "-".join(t)]
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"[^a-z0-9-]", "", c)
        if len(c) >= 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:3]


def _greenhouse_name_ok(token: str, sponsor_name: str) -> bool:
    meta = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}", min_interval=0.2) or {}
    board = core_name(meta.get("name", "")).replace(" ", "")
    want = core_name(sponsor_name).replace(" ", "")
    return bool(board) and board == want


COMMON_WORDS = {
    "build", "quantum", "sample", "impact", "simple", "smart", "bright", "nova", "apex", "pulse", "prime", "core",
    "next", "open", "true", "blue", "green", "red", "one", "first", "global", "insight", "vision", "spark", "edge",
    "nexus", "zen", "flow", "wave", "shift", "point", "path", "bridge", "link", "hub", "base", "stack", "pixel",
    "atlas", "orbit", "fusion", "matrix", "vertex", "summit", "peak", "unity", "bloom", "ember", "echo", "lumen",
}


def _uk_jobs(ats: str, token: str, sponsor_name: str) -> int:
    """UK jobs on the board, or 0 if the adverts don't mention the company (slug belongs to someone else)."""
    try:
        jobs = ATS[ats].fetch(token, uk_only=True) if ats != "smartrecruiters" else []
    except Exception:
        return 0
    if not jobs:
        return 0
    phrase = " ".join(_tokens(sponsor_name))
    core = core_name(sponsor_name)
    text = " ".join((j.description or "") + " " + j.title for j in jobs[:10]).lower()
    squashed = re.sub(r"[^a-z0-9]", "", text)
    if phrase and (phrase in text or phrase.replace(" ", "") in squashed):
        return len(jobs)
    if core and core not in COMMON_WORDS and len(core.replace(" ", "")) >= 5 and core in text:
        return len(jobs)
    return 0


def probe_company(name: str) -> list[tuple[str, str, int]]:
    """[(ats, token, uk_job_count)] for boards that exist for this company."""
    found = []
    for slug in slug_candidates(name):
        for ats in ("greenhouse", "lever", "ashby"):
            try:
                count = ATS[ats].board_exists(slug)
            except Exception:
                continue
            if count and count > 0:
                if ats == "greenhouse" and not _greenhouse_name_ok(slug, name):
                    continue
                uk = _uk_jobs(ats, slug, name)
                if uk:
                    found.append((ats, slug, uk))
        if found:
            break
    return found


TECH_HUBS = re.compile(r"london|cambridge|oxford|manchester|edinburgh|bristol|leeds|glasgow|belfast|reading|"
                       r"brighton|bath|guildford|milton keynes|newcastle|sheffield|birmingham|cardiff", re.I)
STRONG = re.compile(r"\b(technolog(y|ies)|software|labs?|ai|robotics|analytics|cloud|cyber|fintech|platforms?|"
                    r"data|digital|quantum|bio|health|games|studios?|io|app|apps|computing|intelligence)\b", re.I)
WEAK = re.compile(r"consult|recruit|staffing|resourc|outsourc|care\b|trading|import|export|catering|"
                  r"restaurant|construction|logistics|cleaning|security services|it services|it solutions", re.I)


def priority(sp) -> float:
    """How promising a sponsor is for tech job boards (higher = probe first)."""
    score = 0.0
    if TECH_HUBS.search(sp.town or ""):
        score += 2
    score += 1.5 * len(STRONG.findall(sp.name))
    if WEAK.search(sp.name):
        score -= 3
    core = core_name(sp.name).split()
    if 1 <= len(core) <= 2:
        score += 1      # short brandable names are usually product companies
    if not sp.a_rated:
        score -= 2
    return score


def discover(db: DB, register: SponsorRegister, keywords: list[str], max_probes: int = 400,
             extra_names: list[str] | None = None, workers: int = 8, progress=None) -> list[tuple[str, str, str, int]]:
    """Probe up to `max_probes` not-yet-checked sponsors. Returns new boards found."""
    # dream companies and employers already seen in job adverts first, then the most promising sponsors
    names = list(extra_names or [])
    seen_employers = [r[0] for r in db.conn.execute(
        "SELECT DISTINCT sponsor_match FROM jobs WHERE sponsor_match IS NOT NULL AND source IN ('reed','adzuna')")]
    names += seen_employers
    names += [sp.name for sp in sorted(register.tech_like(keywords), key=priority, reverse=True)]
    todo, seen = [], set()
    for n in names:
        key = core_name(n)
        if key and key not in seen and not db.probed(n):
            seen.add(key)
            todo.append(n)
        if len(todo) >= max_probes:
            break
    found = []
    with cf.ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(probe_company, n): n for n in todo}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            name = futures[fut]
            try:
                hits = fut.result()
            except Exception as e:
                log.debug("probe failed for %s: %s", name, e)
                hits = []
            display = re.sub(r"\b(ltd|limited|plc|llp)\b\.?", "", name, flags=re.I).strip(" ,.")
            for ats, token, n in hits:
                taken = db.conn.execute("SELECT company FROM boards WHERE ats=? AND token=?", (ats, token)).fetchone()
                if taken and core_name(taken[0]) != core_name(display):
                    continue  # the slug already belongs to another company: ambiguous, skip
                db.upsert_board(ats, token, display, name, "live", n)
                found.append((display, ats, token, n))
            db.mark_probed(name, ",".join(f"{a}:{t}" for a, t, _ in hits))
            if progress:
                progress(i, len(todo), name, hits)
            if i % 25 == 0:
                db.commit()
    db.commit()
    return found


__all__ = ["discover", "load_seed", "slug_candidates", "probe_company", "is_uk"]
