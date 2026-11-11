"""Recruitment agencies: their adverts hide the real employer, so sponsorship is unknown.

An agency can hold a sponsor licence for its own staff, but the company you would work
for is the one that must sponsor you. So for agency adverts the register match is not
credited: the job stays visible, scores lower on sponsorship, never triggers an
"apply today" alert, and carries a note to ask the recruiter who the client is.
"""
from __future__ import annotations

import re

# Words that mark a recruiter's name (whole words, case-insensitive)
_WORDS = re.compile(
    r"\b(recruitment|recruiting|recruiters?|resourcing|staffing|headhunters?|talent solutions|talent acquisition|"
    r"search (?:and|&) selection|personnel|employment agency|jobs ltd|careers ltd|consultancy group)\b", re.I)

# Common UK technology and general recruiters, as they appear on job boards
KNOWN = {
    "robert half", "viqu", "hays", "reed specialist recruitment", "michael page", "page personnel", "harvey nash",
    "randstad", "adecco", "manpower", "experis", "spencer ogden", "morgan mckinley", "computer futures",
    "nigel frank", "jefferson frank", "tenth revolution", "la fosse", "harnham", "opus recruitment",
    "searchability", "hamilton barnes", "intapeople", "certus", "akkodis", "modis", "sanderson",
    "nicholson glover", "stott and may", "burns sheehan", "haybrook", "ambis", "hunter selection", "huxley",
    "explore group", "understanding recruitment", "oscar associates", "venquis", "gold group", "kforce",
    "pertemps", "search consultancy", "sthree", "hirewell", "mcgregor boyall", "jonathan lee", "anson mccade",
    "frank recruitment", "c4 recruitment", "net talent", "trust in soda", "ioassociates", "office angels",
    "blue arrow", "brook street", "kelly services", "lorien", "eden smith", "piper maddox", "rullion", "matchtech",
    "gattaca", "redline group", "talent international", "oho group", "wilson worldwide", "prospect us",
    "senitor associates", "deerfoot it", "x4 group", "trinnovo", "spectrum it", "carrington blake",
    "henderson scott", "you recruit", "allen associates", "cathcart associates", "hireful",
    # seen on real runs
    "reed", "oscar technology", "mcs group", "candour solutions", "nexus jobs", "jumar solutions",
    "akt", "hackajob", "centre people", "lawrence harvey", "franklin fitch", "client server", "ic resources", "evolution jobs",
}

# Words a recruiter adds after its name for a division ("Hays Technology", "Reed Technology",
# "Randstad Digital", "Adecco IT"). A known single-word name only counts when followed by these.
_DIVISION = {"technology", "technologies", "tech", "it", "digital", "specialist", "specialists", "professional",
             "professionals", "solutions", "talent", "people", "careers", "jobs", "consulting", "associates",
             "partners", "selection", "search", "interim", "contract", "contracts", "engineering", "cyber",
             "data", "life", "sciences", "public", "sector", "education", "healthcare", "permanent"}


def _norm(name: str) -> str:
    name = re.sub(r"\b(ltd|limited|plc|llp|uk|group|global|international)\b\.?", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9& ]+", " ", re.sub(r"\s+", " ", name)).strip()


_KNOWN_N = {_norm(k) for k in KNOWN}


def is_agency(company: str, extra: dict | None = None) -> bool:
    if extra and extra.get("agency") is not None:
        return bool(extra["agency"])
    if _WORDS.search(company or ""):
        return True
    n = _norm(company)
    if not n:
        return False
    if n in _KNOWN_N:
        return True
    for k in _KNOWN_N:
        if n.startswith(k + " "):
            rest = n[len(k) + 1:].split()
            # "robert half technology": any tail after a multi-word name;
            # "hays technology": a single-word name only with a division word after it
            if " " in k or all(w in _DIVISION for w in rest):
                return True
    return False
