"""UK Home Office register of licensed sponsors: download, index and match company names.

Source: https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers
The register is updated every working day. Only employers on it can sponsor a
Skilled Worker visa, so this is the strongest signal we have.
"""
from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterable, Optional

from .http import get_json, session

CONTENT_API = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
REFRESH_SECONDS = 3 * 24 * 3600

LEGAL_SUFFIXES = {
    "ltd", "limited", "plc", "llp", "lp", "llc", "inc", "incorporated", "corp", "corporation",
    "gmbh", "ag", "sa", "sas", "bv", "nv", "ab", "as", "oy", "pty", "co", "company", "the",
}
GENERIC_WORDS = {
    "uk", "gb", "england", "london", "europe", "european", "emea", "international", "global", "group",
    "holdings", "holding", "services", "service", "technologies", "technology", "tech", "labs", "lab",
    "software", "digital", "solutions", "systems", "bank", "financial", "finance", "payments", "payment",
    "operations", "ventures", "research", "studios", "studio", "platforms", "platform", "ai", "io",
    "and", "of", "trading", "enterprises", "network",
    # public sector: "X NHS Trust" vs "X NHS Foundation Trust" on the register
    "nhs", "foundation", "trust", "integrated", "care", "board", "networks", "online", "markets",
}


def _tokens(name: str) -> list[str]:
    name = (name or "").lower().replace("&", " and ")
    name = re.sub(r"\(.*?\)", " ", name)
    name = re.sub(r"\bicb\b", " integrated care board ", name)
    name = re.sub(r"\.(com|co\.uk|io|ai|co)\b", " ", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name.replace(".", ""))
    return [t for t in name.split() if t not in LEGAL_SUFFIXES]


def core_name(name: str) -> str:
    toks = _tokens(name)
    core = [t for t in toks if t not in GENERIC_WORDS]
    return " ".join(core or toks)


@dataclass
class Sponsor:
    name: str
    town: str
    county: str
    rating: str
    route: str

    @property
    def a_rated(self) -> bool:
        return "A rating" in self.rating


class SponsorRegister:
    def __init__(self, rows: Iterable[dict], aliases: dict[str, str] | None = None):
        # aliases: {"Coinbase": "CB Payments Ltd"} for employers that sponsor under another legal name
        self.aliases = {k.lower(): v for k, v in (aliases or {}).items()}
        self.sponsors: list[Sponsor] = []
        for r in rows:
            route = (r.get("Route") or "").strip()
            if route != "Skilled Worker":
                continue
            raw_name = (r.get("Organisation Name") or "").strip()
            sp = Sponsor(raw_name, (r.get("Town/City") or "").strip(), (r.get("County") or "").strip(),
                         (r.get("Type & Rating") or "").strip(), route)
            self.sponsors.append(sp)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, cache_dir: Path, force: bool = False, aliases: dict[str, str] | None = None) -> "SponsorRegister":
        path = cache_dir / "sponsor_register.csv"
        if force or not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS:
            try:
                download(path)
            except Exception as exc:  # keep working from the old copy if gov.uk is down
                if not path.exists():
                    raise RuntimeError(f"Could not download the sponsor register: {exc}") from exc
        with path.open(encoding="utf-8-sig", newline="") as f:
            return cls(csv.DictReader(f), aliases)

    # ------------------------------------------------------------------ index
    @cached_property
    def _index(self) -> dict[str, list[tuple[list[str], Sponsor, bool]]]:
        """first token -> [(tokens, sponsor, is_trading_name)]. Also keyed by the squashed name."""
        idx: dict[str, list[tuple[list[str], Sponsor, bool]]] = {}
        for sp in self.sponsors:
            names = [(sp.name, False)]
            # "ACME LTD T/A Brand" -> index "ACME" and "Brand"
            m = re.split(r"(?:\bt/a\b|\btrading as\b)", sp.name, flags=re.I)
            if len(m) > 1:
                names = [(m[0], False), (m[1], True)]
            for n, is_alias in names:
                toks = _tokens(n)
                if toks:
                    idx.setdefault(toks[0], []).append((toks, sp, is_alias))
                    squashed = "".join(toks)
                    if squashed != toks[0]:
                        idx.setdefault("#" + squashed, []).append((toks, sp, is_alias))
        return idx

    def match(self, company: str) -> Optional[Sponsor]:
        """Best register entry for an employer name, or None.

        Matches exact names, and names that only differ by generic words,
        e.g. "Monzo" -> "Monzo Bank Ltd", "Stripe" -> "Stripe Payments UK Ltd".
        """
        if company.lower() in self.aliases:
            company = self.aliases[company.lower()]
        toks = _tokens(company)
        if not toks:
            return None
        best: tuple[float, Optional[Sponsor]] = (0, None)
        candidates = self._index.get(toks[0], []) + self._index.get("#" + "".join(toks), [])
        for cand_toks, sp, is_alias in candidates:
            if "".join(cand_toks) == "".join(toks):
                score = 3
            elif cand_toks[: len(toks)] == toks and all(t in GENERIC_WORDS for t in cand_toks[len(toks):]):
                score = 2
            elif toks[: len(cand_toks)] == cand_toks and all(t in GENERIC_WORDS for t in toks[len(cand_toks):]):
                score = 2
            elif core_name(" ".join(cand_toks)) == core_name(company) and core_name(company):
                score = 1
            else:
                continue
            if sp.a_rated:
                score += 0.5
            if is_alias:
                score -= 1.25
            if score > best[0]:
                best = (score, sp)
        return best[1]

    def is_sponsor(self, company: str) -> bool:
        return self.match(company) is not None

    def tech_like(self, keywords: list[str]) -> list[Sponsor]:
        """Sponsors whose names suggest a tech company (for job-board discovery)."""
        pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.I)
        return [s for s in self.sponsors if pat.search(s.name)]


def download(path: Path) -> Path:
    meta = get_json(CONTENT_API)
    url = None
    for att in (meta or {}).get("details", {}).get("attachments", []):
        if str(att.get("url", "")).endswith(".csv"):
            url = att["url"]
            break
    if not url:
        raise RuntimeError("No CSV attachment found on the gov.uk sponsor register page")
    r = session().get(url, timeout=120)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return path


def from_csv_text(text: str) -> SponsorRegister:
    return SponsorRegister(csv.DictReader(io.StringIO(text)))
