"""Text helpers: HTML to plain text, normalisation."""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    # Greenhouse returns HTML-escaped HTML
    if "&lt;" in raw and "<" not in raw[:200]:
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(["p", "div", "br", "h1", "h2", "h3", "h4", "ul", "ol"]):
        tag.insert_after("\n")
    text = soup.get_text()
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ ]+", " ", (s or "").lower())).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]
