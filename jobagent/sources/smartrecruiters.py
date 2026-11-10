"""SmartRecruiters public Posting API: https://developers.smartrecruiters.com/docs/posting-api"""
from __future__ import annotations

from ..http import get_json
from ..models import Job
from ..text import html_to_text
from ..visa import parse_salary
from .base import parse_dt, work_mode

API = "https://api.smartrecruiters.com/v1/companies/{token}/postings"


def board_exists(token: str) -> int:
    data = get_json(API.format(token=token), params={"limit": 1}, min_interval=0.2)
    return int((data or {}).get("totalFound", 0)) if data else -1


def fetch(token: str, company: str | None = None, uk_only: bool = True, detail_limit: int = 60,
          want=None, known: set | None = None) -> list[Job]:
    """`want(title) -> bool` skips irrelevant titles before the (slow) detail request."""
    params = {"limit": 100, "offset": 0}
    if uk_only:
        params["country"] = "gb"
    jobs = []
    while True:
        data = get_json(API.format(token=token), params=params) or {}
        content = data.get("content", [])
        for j in content:
            if want and not want(j.get("name", "")):
                continue
            if known and j["id"] in known:
                continue
            loc = j.get("location") or {}
            loc_s = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country", "").upper()) if x)
            desc = ""
            if len(jobs) < detail_limit:  # the list endpoint has no description
                det = get_json(f"{API.format(token=token)}/{j['id']}") or {}
                secs = (det.get("jobAd") or {}).get("sections") or {}
                desc = "\n\n".join(html_to_text((secs.get(k) or {}).get("text", ""))
                                   for k in ("jobDescription", "qualifications", "additionalInformation"))
            lo, hi = parse_salary(desc)
            jobs.append(Job(
                source="smartrecruiters", source_id=j["id"], company=company or (j.get("company") or {}).get("name", token),
                title=j.get("name", "").strip(), location=loc_s,
                url=f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                apply_url=f"https://jobs.smartrecruiters.com/{token}/{j['id']}", description=desc,
                salary_min=lo, salary_max=hi, remote="remote" if loc.get("remote") else work_mode(loc_s),
                posted_at=parse_dt(j.get("releasedDate")), ats="smartrecruiters", ats_token=token,
            ))
        params["offset"] += len(content)
        if not content or params["offset"] >= data.get("totalFound", 0) or params["offset"] >= 300:
            break
    return jobs
