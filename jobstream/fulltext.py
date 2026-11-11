"""Full advert text for jobs that arrive as a snippet (Adzuna's API gives about 500 characters).

Claude judges a job far better on the whole advert, so before an assessment the snippet is
replaced with the full text where it can be found:
  1. the job's schema.org JobPosting data (most employer and ATS pages publish it), or
  2. the advert body on Adzuna's own job page.
One polite request per page; if nothing longer turns up, the snippet is kept.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from .models import Job
from .text import html_to_text

SHORT = 1500          # descriptions shorter than this are treated as snippets


def _postings(data) -> list[dict]:
    if isinstance(data, list):
        return [p for d in data for p in _postings(d)]
    if not isinstance(data, dict):
        return []
    if "@graph" in data:
        return _postings(data["@graph"])
    kind = data.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return [data] if "JobPosting" in kinds else []


def from_html(page: str) -> str:
    """The advert text in a job page, or ''."""
    soup = BeautifulSoup(page or "", "html.parser")
    best = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        for p in _postings(data):
            text = html_to_text(str(p.get("description") or ""))
            if len(text) > len(best):
                best = text
    if best:
        return best
    body = soup.find(class_=re.compile(r"\badp-body\b"))      # Adzuna's advert body
    return html_to_text(str(body)) if body else ""


def _pages(job: Job) -> list[str]:
    urls = []
    if job.source == "adzuna" and job.source_id:
        urls.append(f"https://www.adzuna.co.uk/jobs/details/{job.source_id}")
    if job.url:
        urls.append(job.url)
    return list(dict.fromkeys(urls))


def fetch(job: Job, timeout: int = 20) -> Optional[str]:
    """Full text for a job whose description is short, or None."""
    from .http import session

    have = len(job.description or "")
    if have >= SHORT:
        return None
    for url in _pages(job):
        try:
            r = session().get(url, timeout=timeout, allow_redirects=True)
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
                continue
            text = from_html(r.text)
        except Exception:
            continue
        if len(text) > max(have + 200, 600):
            return text
    return None
