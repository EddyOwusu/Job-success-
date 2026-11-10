"""Workday career sites (banks, insurers, pharma, retailers, media, some universities).

A board token is "<host>|<site>", taken from the careers URL, e.g.
https://barclays.wd3.myworkdayjobs.com/en-US/External_Career_Site_Barclays
-> "barclays.wd3.myworkdayjobs.com|External_Career_Site_Barclays"
"""
from __future__ import annotations

import re

from ..http import _throttle, session
from ..models import Job
from ..text import html_to_text
from ..visa import parse_salary
from .base import is_uk, parse_dt, work_mode


def _api(token: str) -> tuple[str, str]:
    host, site = token.split("|", 1)
    tenant = host.split(".")[0]
    return f"https://{host}/wday/cxs/{tenant}/{site}", host


def parse_url(url: str) -> str | None:
    m = re.search(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", url)
    return f"{m.group(1)}|{m.group(2)}" if m else None


def _search(token: str, text: str, limit: int = 20, offset: int = 0) -> dict:
    api, host = _api(token)
    _throttle(host, 0.5)
    r = session().post(f"{api}/jobs", json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": text},
                       timeout=30)
    return r.json() if r.status_code == 200 else {}


def board_exists(token: str) -> int:
    return int(_search(token, "", limit=1).get("total") or 0) or -1


def fetch(token: str, company: str | None = None, uk_only: bool = True, want=None,
          queries: list[str] | None = None, details: int = 40, known: set | None = None) -> list[Job]:
    """`known`: advert paths already stored (extra["path"]); skipped before the slow detail request."""
    api, host = _api(token)
    seen, postings = set(), []
    for q in (queries or ["software engineer", "developer", "data engineer"])[:6]:
        for offset in (0, 20):
            data = _search(token, q, 20, offset)
            for p in data.get("jobPostings", []):
                if p.get("externalPath") in seen:
                    continue
                seen.add(p.get("externalPath"))
                if known and p.get("externalPath") in known:
                    continue
                if want and not want(p.get("title", "")):
                    continue
                loc = p.get("locationsText", "")
                if uk_only and not re.search(r"\d+ locations", loc, re.I) and not is_uk(loc):
                    continue
                postings.append(p)
            if len(data.get("jobPostings", [])) < 20:
                break
    jobs = []
    for p in postings[:details]:
        _throttle(host, 0.5)
        r = session().get(f"{api}{p['externalPath']}", timeout=30)
        if r.status_code != 200:
            continue
        info = (r.json() or {}).get("jobPostingInfo", {})
        locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
        country = (info.get("country") or {}).get("descriptor", "")
        loc = "; ".join(x for x in locs if x) + (f" ({country})" if country else "")
        if uk_only and not (is_uk(loc) or country == "United Kingdom"):
            continue
        desc = html_to_text(info.get("jobDescription", ""))
        lo, hi = parse_salary(desc)
        url = info.get("externalUrl") or f"https://{host}/{token.split('|')[1]}{p['externalPath']}"
        jobs.append(Job(
            source="workday", source_id=f"{host.split('.')[0]}:{info.get('jobReqId') or p['externalPath'].split('_')[-1]}",
            company=company or host.split(".")[0], title=info.get("title") or p.get("title", ""), location=loc,
            url=url, apply_url=url + "/apply" if not url.endswith("/apply") else url, description=desc,
            salary_min=lo, salary_max=hi, remote=work_mode(loc, (info.get("remoteType") or "")),
            posted_at=parse_dt(info.get("startDate")), ats="workday", ats_token=token,
            extra={"sector": "corporate", "path": p["externalPath"]},
        ))
    return jobs
