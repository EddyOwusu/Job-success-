"""Ashby public Job Posting API: https://developers.ashbyhq.com/docs/public-job-posting-api"""
from __future__ import annotations

from ..http import get_json
from ..models import Job
from ..visa import parse_salary
from .base import is_uk, parse_dt

API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def board_exists(token: str) -> int:
    data = get_json(API.format(token=token), min_interval=0.2)
    return len((data or {}).get("jobs", [])) if data else -1


def _addr(a) -> str:
    pa = (a or {}).get("postalAddress") or {}
    return ", ".join(x for x in (pa.get("addressLocality"), pa.get("addressRegion"), pa.get("addressCountry")) if x)


def fetch(token: str, company: str | None = None, uk_only: bool = True) -> list[Job]:
    data = get_json(API.format(token=token), params={"includeCompensation": "true"})
    jobs = []
    for j in (data or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", ""), _addr(j.get("address"))]
        for sec in j.get("secondaryLocations", []) or []:
            locs += [sec.get("location", ""), _addr(sec.get("address"))]
        loc = "; ".join(dict.fromkeys(x for x in locs if x))
        if uk_only and not is_uk(loc):
            continue
        desc = j.get("descriptionPlain", "") or ""
        comp = (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary") or ""
        lo, hi = parse_salary(comp or desc)
        jobs.append(Job(
            source="ashby", source_id=j["id"], company=company or token, title=j.get("title", "").strip(),
            location=loc, url=j.get("jobUrl", ""), apply_url=j.get("applyUrl", ""), description=desc,
            salary_min=lo, salary_max=hi, remote=(j.get("workplaceType") or "").lower() or None,
            posted_at=parse_dt(j.get("publishedAt")), ats="ashby", ats_token=token,
            extra={"department": j.get("department"), "team": j.get("team"), "employmentType": j.get("employmentType")},
        ))
    return jobs
