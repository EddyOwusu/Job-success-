"""jobs.ac.uk: UK universities, research institutes and colleges.

Universities are licensed sponsors and hire research software engineers,
developers, data engineers, systems and infrastructure staff.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import session
from ..models import Job
from ..text import html_to_text
from ..visa import parse_salary
from .base import abroad, work_mode

BASE = "https://www.jobs.ac.uk"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; jobagent personal job search)"}


def available() -> bool:
    return True


def advert(url: str) -> str:
    r = session().get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    parts = [el.get_text("\n", strip=True) for el in s.select(".j-advert-details__container, #job-description")]
    return "\n\n".join(p for p in parts if p)


def search(query: str, location: str = "", pages: int = 1, details: int = 20, want=None,
           known: set | None = None, stats: dict | None = None) -> list[Job]:
    jobs: list[Job] = []
    detailed = 0
    for page in range(pages):
        params = {"keywords": query, "startIndex": 1 + page * 25, "pageSize": 25}
        if location and "remote" not in location.lower():
            params["location"] = location
        r = session().get(f"{BASE}/search/", params=params, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            break
        s = BeautifulSoup(r.text, "html.parser")
        results = s.select(".j-search-result__result")
        if stats is not None:
            stats["seen"] = stats.get("seen", 0) + len(results)
        for res in results:
            a = res.select_one(".j-search-result__text a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if want and not want(title):
                continue
            url = urljoin(BASE, a["href"])
            if known and (res.get("data-advert-id") or url.split("/job/")[-1].split("/")[0]) in known:
                continue
            employer = (res.select_one(".j-search-result__employer") or a).get_text(" ", strip=True)
            dept = (res.select_one(".j-search-result__department") or a).get_text(" ", strip=True)
            block = res.get_text("\n", strip=True)
            loc = re.search(r"Location:\s*(.+)", block)
            loc = loc.group(1).strip() if loc else ""
            if abroad(f"{loc} {employer}"):
                continue  # jobs.ac.uk also lists posts at overseas campuses
            sal = (res.select_one(".j-search-result__info") or a).get_text(" ", strip=True)
            lo, hi = parse_salary(sal)
            desc = f"{dept}\n{sal}"
            if detailed < details:
                try:
                    desc = advert(url) or desc
                    detailed += 1
                except Exception:
                    pass
            jobs.append(Job(
                source="jobsacuk", source_id=res.get("data-advert-id") or url.split("/job/")[-1].split("/")[0],
                company=employer, title=title, location=loc or "UK", url=url, apply_url=url,
                description=desc, salary_min=lo, salary_max=hi, remote=work_mode(loc, desc[:1500]),
                extra={"sector": "university", "department": dept},
            ))
        if len(results) < 25:
            break
    return jobs


__all__ = ["search", "advert", "html_to_text"]
