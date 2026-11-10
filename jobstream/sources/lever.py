"""Lever public Postings API: https://github.com/lever/postings-api"""
from __future__ import annotations

from ..http import get_json
from ..models import Job
from ..visa import parse_salary
from .base import is_uk, parse_dt, work_mode

API = "https://api.lever.co/v0/postings/{token}"


def board_exists(token: str) -> int:
    data = get_json(API.format(token=token), params={"mode": "json", "limit": 50}, min_interval=0.2)
    return len(data) if isinstance(data, list) else -1


def fetch(token: str, company: str | None = None, uk_only: bool = True, stats: dict | None = None) -> list[Job]:
    data = get_json(API.format(token=token), params={"mode": "json"})
    jobs = []
    if stats is not None:
        stats["seen"] = len(data) if isinstance(data, list) else 0
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ""
        all_locs = ", ".join(cats.get("allLocations") or []) or loc
        if uk_only and not (is_uk(all_locs) or (j.get("country") or "").upper() == "GB"):
            continue
        parts = [j.get("descriptionPlain", "")]
        for lst in j.get("lists", []) or []:
            from ..text import html_to_text
            parts.append(f"\n{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}")
        parts.append(j.get("additionalPlain", ""))
        desc = "\n".join(p for p in parts if p).strip()
        sal = j.get("salaryRange") or {}
        lo, hi = (sal.get("min"), sal.get("max")) if sal.get("currency") == "GBP" else parse_salary(desc)
        jobs.append(Job(
            source="lever", source_id=j["id"], company=company or token, title=j.get("text", "").strip(),
            location=all_locs, url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl", ""),
            description=desc, salary_min=lo, salary_max=hi,
            remote=(j.get("workplaceType") or "").lower() or work_mode(all_locs),
            posted_at=parse_dt(j.get("createdAt")), ats="lever", ats_token=token,
            extra={"team": cats.get("team"), "commitment": cats.get("commitment")},
        ))
    return jobs
