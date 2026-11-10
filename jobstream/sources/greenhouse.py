"""Greenhouse public Job Board API: https://developers.greenhouse.io/job-board.html"""
from __future__ import annotations

from ..http import get_json
from ..models import Job
from ..text import html_to_text
from ..visa import parse_salary
from .base import is_uk, parse_dt, work_mode

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def board_exists(token: str) -> int:
    data = get_json(API.format(token=token), min_interval=0.2)
    return len((data or {}).get("jobs", [])) if data else -1


def fetch(token: str, company: str | None = None, uk_only: bool = True, stats: dict | None = None) -> list[Job]:
    data = get_json(API.format(token=token), params={"content": "true"})
    jobs = []
    if stats is not None:
        stats["seen"] = len((data or {}).get("jobs", []))
    for j in (data or {}).get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) or [])
        full_loc = loc if not offices or offices in loc else f"{loc}; {offices}"
        if uk_only and not is_uk(full_loc):
            continue
        desc = html_to_text(j.get("content", ""))
        lo, hi = parse_salary(desc)
        jobs.append(Job(
            source="greenhouse", source_id=str(j["id"]), company=company or j.get("company_name") or token,
            title=j.get("title", "").strip(), location=full_loc, url=j.get("absolute_url", ""),
            apply_url=j.get("absolute_url", ""), description=desc, salary_min=lo, salary_max=hi,
            remote=work_mode(full_loc, j.get("title", "")),
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            ats="greenhouse", ats_token=token,
            extra={"departments": [d.get("name") for d in j.get("departments", []) or []]},
        ))
    return jobs


def questions(token: str, job_id: str) -> dict:
    """The application form definition for one job (field names, labels, options)."""
    return get_json(f"{API.format(token=token)}/{job_id}", params={"questions": "true"}) or {}
