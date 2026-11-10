"""Adzuna Jobs API (free key): https://developer.adzuna.com/"""
from __future__ import annotations

import os

from ..http import get_json
from ..models import Job
from .base import parse_dt, work_mode

API = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"


def available() -> bool:
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def search(query: str, location: str = "", pages: int = 2, max_days_old: int = 30) -> list[Job]:
    jobs = []
    for page in range(1, pages + 1):
        params = {
            "app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"],
            "what": query, "results_per_page": 50, "max_days_old": max_days_old,
            "category": "it-jobs", "content-type": "application/json",
        }
        if location and "remote" not in location.lower():
            params["where"] = location
        data = get_json(API.format(page=page), params=params, min_interval=1.0) or {}
        results = data.get("results", [])
        for r in results:
            loc = (r.get("location") or {}).get("display_name", "")
            jobs.append(Job(
                source="adzuna", source_id=str(r["id"]), company=(r.get("company") or {}).get("display_name", "").strip(),
                title=r.get("title", "").strip(), location=loc, url=r.get("redirect_url", ""),
                apply_url=r.get("redirect_url", ""), description=r.get("description", ""),  # snippet only
                salary_min=r.get("salary_min"), salary_max=r.get("salary_max"),
                remote=work_mode(loc, r.get("title", "")), posted_at=parse_dt(r.get("created")),
                extra={"snippet_only": True},
            ))
        if len(results) < 50:
            break
    return jobs
