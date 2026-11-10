"""Reed.co.uk Jobseeker API (free key): https://www.reed.co.uk/developers/jobseeker"""
from __future__ import annotations

import os

from ..http import get_json
from ..models import Job
from .base import parse_dt, work_mode

API = "https://www.reed.co.uk/api/1.0"


def available() -> bool:
    return bool(os.environ.get("REED_API_KEY"))


def search(query: str, location: str = "", max_results: int = 100, details: int = 40, want=None) -> list[Job]:
    auth = (os.environ["REED_API_KEY"], "")
    params = {"keywords": query, "resultsToTake": min(max_results, 100)}
    if location and "remote" not in location.lower():
        params.update(locationName=location, distanceFromLocation=15)
    data = get_json(f"{API}/search", params=params, auth=auth, min_interval=0.5) or {}
    jobs = []
    for i, r in enumerate(data.get("results", [])):
        desc = r.get("jobDescription", "") or ""
        if i < details:  # the search result only has a snippet
            det = get_json(f"{API}/jobs/{r['jobId']}", auth=auth, min_interval=0.5) or {}
            from ..text import html_to_text
            desc = html_to_text(det.get("jobDescription", "")) or desc
        # Reed dates are dd/mm/yyyy
        posted = None
        if r.get("date"):
            d, m, y = r["date"].split("/")
            posted = parse_dt(f"{y}-{m}-{d}")
        jobs.append(Job(
            source="reed", source_id=str(r["jobId"]), company=r.get("employerName", "").strip(),
            title=r.get("jobTitle", "").strip(), location=r.get("locationName", ""),
            url=r.get("jobUrl", ""), apply_url=r.get("jobUrl", ""), description=desc,
            salary_min=r.get("minimumSalary"), salary_max=r.get("maximumSalary"),
            remote=work_mode(r.get("locationName", ""), desc[:500]), posted_at=posted,
            extra={"recruiter": r.get("employerName"), "applications": r.get("applications")},
        ))
    return jobs
