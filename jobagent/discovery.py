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
    if core and len(core[0]) >= 6:
        cands.append(core[0])
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"[^a-z0-9-]", "", c)
        if len(c) >= 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:3]


def _greenhouse_name_ok(token: str, sponsor_name: str) -> bool:
    meta = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}", min_interval=0.2) or {}
    board = core_name(meta.get("name", ""))
    want = core_name(sponsor_name)
    return bool(board) and (board == want or board.split()[0] == want.split()[0])


def _uk_jobs(ats: str, token: str) -> int:
    try:
        return len(ATS[ats].fetch(token, uk_only=True)) if ats != "smartrecruiters" else 0
    except Exception:
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
                uk = _uk_jobs(ats, slug)
                if uk:
                    found.append((ats, slug, uk))
        if found:
            break
    return found


def discover(db: DB, register: SponsorRegister, keywords: list[str], max_probes: int = 400,
             extra_names: list[str] | None = None, workers: int = 8, progress=None) -> list[tuple[str, str, str, int]]:
    """Probe up to `max_probes` not-yet-checked sponsors. Returns new boards found."""
    names = list(extra_names or [])
    for sp in register.tech_like(keywords):
        names.append(sp.name)
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
