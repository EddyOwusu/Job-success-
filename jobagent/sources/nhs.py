"""NHS Jobs (England and Wales): public search API + advert pages.

The NHS is one of the UK's biggest sponsors and hires thousands of developers,
data engineers, analysts and IT staff. Adverts state the pay band and, often,
whether Skilled Worker sponsorship is possible.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from ..http import session
from ..models import Job
from .base import parse_dt, work_mode

API = "https://www.jobs.nhs.uk/api/v1/search_xml"


def available() -> bool:
    return True


def _salary(s: str) -> tuple[float | None, float | None]:
    nums = [float(x.replace(",", "")) for x in re.findall(r"£\s?([\d,]+(?:\.\d+)?)", s or "")]
    nums = [n for n in nums if n > 10000]
    if not nums:
        return None, None
    return min(nums), max(nums)


def advert(url: str) -> dict:
    """Full advert text, location and person-specification criteria from an NHS Jobs page."""
    r = session().get(url, timeout=30)
    r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    parts = []
    for sec in ("job_overview", "job_description", "job_description_large", "about_organisation"):
        for el in s.find_all(id=sec):
            parts.append(el.get_text("\n", strip=True))
    criteria = []
    for el in s.find_all(id=re.compile(r"^(essential|desirable)_skill_\d+_criteria_\d+")):
        kind = "Essential" if el["id"].startswith("essential") else "Desirable"
        criteria.append(f"{kind}: {el.get_text(' ', strip=True)}")
    criteria = list(dict.fromkeys(criteria))  # the page repeats them for mobile and desktop
    town_el = s.find(id="employer_town")
    town = town_el.get_text(" ", strip=True) if town_el else ""
    apply = s.find(id="apply-ats-direct")
    text = "\n\n".join(dict.fromkeys(p for p in parts if p))
    if criteria:
        text += "\n\nPerson specification\n" + "\n".join(f"- {c}" for c in criteria)
    return {"text": text, "criteria": criteria, "town": town,
            "apply_url": apply.get("href") if apply and apply.get("href") else url}


def search(query: str, location: str = "", pages: int = 2, details: int = 25, want=None,
           known: set | None = None) -> list[Job]:
    """`known`: source ids already stored; they are skipped so repeat searches are fast."""
    jobs: list[Job] = []
    detailed = 0
    for page in range(1, pages + 1):
        params = {"keyword": query, "page": page}
        if location and "remote" not in location.lower():
            params["location"] = location
        r = session().get(API, params=params, timeout=30)
        if r.status_code != 200:
            break
        root = ET.fromstring(r.content)
        rows = root.findall("vacancyDetails")
        for v in rows:
            g = lambda tag: (v.findtext(tag) or "").strip()
            title = g("title")
            if want and not want(title):
                continue
            if known and (g("id") or g("reference")) in known:
                continue
            lo, hi = _salary(g("salary")) if g("salary") else _salary(g("description"))
            url = g("url")
            desc, extra, loc, apply_url = g("description"), {"sector": "nhs", "contract": g("type"),
                                                             "closes": g("closeDate"), "reference": g("reference")}, g("locations"), url
            if detailed < details and url:
                try:
                    ad = advert(url)
                    desc = ad["text"] or desc
                    loc = loc or ad["town"]
                    apply_url = ad["apply_url"]
                    extra["criteria"] = ad["criteria"]
                    detailed += 1
                except Exception:
                    pass
            jobs.append(Job(
                source="nhs", source_id=g("id") or g("reference"), company=g("employer"), title=title,
                location=(loc or "England") + ", UK", url=url, apply_url=apply_url, description=desc,
                salary_min=lo, salary_max=hi, remote=work_mode(desc[:1500]), posted_at=parse_dt(g("postDate")),
                extra=extra,
            ))
        if len(rows) < 10:
            break
    return jobs
