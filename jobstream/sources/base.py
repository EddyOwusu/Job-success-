"""Common helpers for job sources."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

UK_PLACES = (
    "united kingdom|\\buk\\b|u\\.k\\.|great britain|england|scotland|wales|northern ireland|london|manchester|"
    "edinburgh|glasgow|cambridge|oxford|bristol|leeds|birmingham|belfast|cardiff|newcastle|sheffield|"
    "nottingham|liverpool|reading|brighton|milton keynes|guildford|bath|york|leicester|southampton|"
    "aberdeen|dundee|swansea|coventry|exeter|norwich|cheltenham|harwell|warwick|slough|basingstoke"
)
# Same-name places abroad: "New York", "Cambridge, MA", "London, Ontario", "Birmingham, AL"...
_NOT_UK = re.compile(
    r"new york|\b(usa|united states|canada|ontario|australia|new south wales)\b|"
    r",\s*(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|on|bc)\b",
    re.I,
)
_UK_RE = re.compile(UK_PLACES, re.I)


def is_uk(location: str, country_code: Optional[str] = None) -> bool:
    if country_code:
        return country_code.upper() in ("GB", "UK")
    loc = location or ""
    for piece in re.split(r"[;|/]| or |\band\b", loc):
        if _UK_RE.search(piece) and not _NOT_UK.search(piece):
            return True
    # "Remote - Europe/EMEA" without the UK named is usually hired via an employer-of-record abroad,
    # which doesn't come with a UK visa, so it doesn't count.
    return False


def work_mode(*texts: str) -> Optional[str]:
    t = " ".join(x or "" for x in texts).lower()
    if "hybrid" in t:
        return "hybrid"
    if "remote" in t:
        return "remote"
    if "on-site" in t or "onsite" in t or "in office" in t or "in-office" in t:
        return "onsite"
    return None


def parse_dt(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value).astimezone()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


_ABROAD = re.compile(
    r"\b(uae|united arab emirates|dubai|abu dhabi|sharjah|qatar|doha|saudi|riyadh|oman|bahrain|kuwait|egypt|"
    r"vietnam|hanoi|ho chi minh|china|beijing|shanghai|ningbo|suzhou|hong kong|macau|singapore|malaysia|"
    r"kuala lumpur|india|pakistan|nigeria|kenya|ghana|south africa|japan|korea|taiwan|thailand|indonesia|"
    r"australia|new zealand|canada|usa|united states|ireland|dublin|netherlands|germany|france|spain|italy|"
    r"switzerland|sweden|norway|denmark|finland|belgium|austria|portugal|poland|czech|greece|cyprus|malta|"
    r"luxembourg|kazakhstan|uzbekistan|mexico|brazil|chile)\b", re.I)


def abroad(location: str) -> bool:
    """True when a location names a place outside the UK (and no UK place)."""
    loc = location or ""
    # "University of Nottingham Ningbo China" names a UK city, so only explicit UK words count here
    return bool(_ABROAD.search(loc)) and not re.search(
        r"\b(uk|united kingdom|england|scotland|wales|northern ireland|london)\b", loc, re.I)

