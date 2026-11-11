"""Which UK work-visa routes are open to you, checked against live gov.uk pages.

Sponsorship by an employer (Skilled Worker) is the main road, but not the only one:
  - Skilled Worker, new-entrant rate: a lower salary bar if you are under 26 or a recent student
  - Scale-up Worker: sponsored for 6 months, then free to change employer
  - High Potential Individual (HPI): 2 years of work rights with no sponsor, if your
    degree is from a university on the Home Office's global list
  - Graduate visa: if you studied in the UK
  - Youth Mobility Scheme / India Young Professionals: by nationality and age
  - Global Talent: by endorsement

This is information to point you at the right page, not immigration advice. Rules
and figures change: every result links to the gov.uk page it came from.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from .http import get_json
from .models import Profile

GOV = "https://www.gov.uk"
CACHE_TTL = 7 * 24 * 3600


@dataclass
class Route:
    name: str
    status: str                 # likely | possible | unlikely | not_eligible | check
    summary: str
    details: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    link: str = ""
    needs_sponsor: bool = True


# ---------------------------------------------------------------------------- gov.uk helpers
def _guide(slug: str, cache_dir: Path) -> dict[str, str]:
    """{part slug: plain text} for a gov.uk guide, cached for a week."""
    cache = cache_dir / f"govuk-{slug.replace('/', '_')}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return json.loads(cache.read_text(encoding="utf-8"))
    data = get_json(f"{GOV}/api/content/{slug}") or {}
    parts = {p["slug"]: BeautifulSoup(p.get("body", ""), "html.parser").get_text(" ", strip=True)
             for p in data.get("details", {}).get("parts", [])}
    if not parts and data.get("details", {}).get("body"):
        parts = {"body": BeautifulSoup(data["details"]["body"], "html.parser").get_text(" ", strip=True)}
    parts["_html_eligibility"] = next((p.get("body", "") for p in data.get("details", {}).get("parts", [])
                                       if p["slug"] == "eligibility"), "")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(parts), encoding="utf-8")
    return parts


def _money(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text or "")
    return int(m.group(1).replace(",", "")) if m else None


def live_thresholds(cache_dir: Path) -> dict[str, Optional[int]]:
    """Salary figures as gov.uk states them today (None if the page wording changed)."""
    out: dict[str, Optional[int]] = {"general": None, "new_entrant": None, "scaleup": None, "transitional": None}
    try:
        sw = _guide("skilled-worker-visa", cache_dir)
        out["general"] = _money(sw.get("your-job", ""), r"highest of:\s*£([\d,]+) per year")
        out["new_entrant"] = _money(sw.get("when-you-can-be-paid-less", ""), r"salary is at least £([\d,]+) per year")
        out["transitional"] = _money(sw.get("certificate-of-sponsorship-before-4-april-2024", ""),
                                     r"higher of £([\d,]+) or the lower going rate")
        su = _guide("scale-up-worker-visa", cache_dir)
        out["scaleup"] = _money(su.get("your-job", ""), r"following 2 options:\s*£([\d,]+) per year")
    except Exception:
        pass
    return out


def _norm_uni(name: str) -> str:
    name = re.sub(r"\(.*?\)", " ", (name or "").lower())
    name = name.replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", re.sub(r"\bthe\b", " ", name)).strip()


def hpi_lists(cache_dir: Path) -> dict[int, list[tuple[str, str]]]:
    """{list year: [(university, country)]}. List year N covers awards from 1 Nov N to 31 Oct N+1."""
    cache = cache_dir / "govuk-hpi-lists.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return {int(k): [tuple(x) for x in v] for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    guide = _guide("high-potential-individual-visa", cache_dir)
    soup = BeautifulSoup(guide.get("_html_eligibility", ""), "html.parser")
    lists: dict[int, list[tuple[str, str]]] = {}
    for a in soup.find_all("a"):
        m = re.search(r"global-universities-list-(\d{4})$", a.get("href", ""))
        if not m:
            continue
        page = get_json(f"{GOV}/api/content{a['href'].replace(GOV, '')}") or {}
        body = BeautifulSoup(page.get("details", {}).get("body", ""), "html.parser")
        rows = []
        for tr in body.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2:
                rows.append((re.sub(r"\s+", " ", cells[0]), cells[1]))
        if rows:
            lists[int(m.group(1))] = rows
    if lists:
        cache.write_text(json.dumps(lists), encoding="utf-8")
    return lists


def hpi_match(institution: str, lists: dict[int, list[tuple[str, str]]], years: list[int]) -> dict[int, Optional[str]]:
    """{list year: matched university name or None}."""
    want = _norm_uni(institution)
    out: dict[int, Optional[str]] = {}
    for y in years:
        hit = None
        for name, _country in lists.get(y, []):
            n = _norm_uni(name)
            abbr = re.findall(r"\(([^)]+)\)", name)
            if want and (n == want or (len(want) > 8 and (want in n or n in want))
                         or any(want == _norm_uni(x) for x in abbr)):
                hit = name
                break
        out[y] = hit
    return out


def _age(dob: Optional[str], today: date) -> Optional[int]:
    try:
        d = date.fromisoformat(dob) if dob else None
    except ValueError:
        return None
    if not d:
        return None
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


# ---------------------------------------------------------------------------- the check
def check(profile: Profile, settings: dict, cache_dir: Path, scaleup_count: int = 0,
          today: Optional[date] = None) -> list[Route]:
    today = today or date.today()
    v, edu = profile.visa, profile.education
    sp = settings["sponsorship"]
    status_text = (v.current_status or "").lower()
    age = _age(v.date_of_birth, today)
    live = live_thresholds(cache_dir)
    routes: list[Route] = []

    # ---- Skilled Worker (+ new entrant)
    drift = []
    for key, setting in (("general", "general_threshold_gbp"), ("new_entrant", "new_entrant_threshold_gbp"),
                         ("scaleup", "scaleup_threshold_gbp"), ("transitional", "transitional_threshold_gbp")):
        if live.get(key) and live[key] != sp.get(setting):
            drift.append(f"gov.uk now says £{live[key]:,} for {setting}; your settings say £{sp.get(setting):,}. "
                         f"Update config/settings.yaml.")
    reasons = []
    if age is not None and age < 26:
        reasons.append(f"you're {age} (under 26)")
    if "student" in status_text or "graduate visa" in status_text or "graduate route" in status_text:
        reasons.append("you're on (or recently held) a Student or Graduate visa")
    sw = Route("Skilled Worker", "likely",
               f"The main route: a job offer from a licensed sponsor paying at least £{sp['general_threshold_gbp']:,} "
               f"(or the job's going rate, if higher).",
               link=f"{GOV}/skilled-worker-visa/your-job")
    if reasons:
        sw.details.append(f"New-entrant rate: you may qualify because {' and '.join(reasons)}. The minimum drops to "
                          f"£{sp['new_entrant_threshold_gbp']:,} (and 70% of the going rate). Time on this rate is "
                          f"capped at 4 years in total, including any Graduate visa.")
        if not v.new_entrant:
            sw.next_steps.append("Set visa.new_entrant: true in config/profile.yaml to reopen lower-paid jobs.")
    elif age is None and not v.new_entrant:
        sw.details.append("Add visa.date_of_birth to your profile to check the under-26 new-entrant rate "
                          f"(£{sp['new_entrant_threshold_gbp']:,} minimum).")
    from .visa import transitional
    tr = transitional(v)
    on_route = "skilled worker" in status_text
    if tr["lower_salary"]:
        # the transitional floor is already below the new-entrant rate, so those notes don't apply
        sw.details = [d for d in sw.details if not d.startswith(("New-entrant rate", "Add visa.date_of_birth"))]
        sw.next_steps = [n for n in sw.next_steps if "new_entrant" not in n]
        sw.summary = (f"You are already on this route, so moving to a new employer means a new certificate of sponsorship and an "
                      f"application to update your visa. Your salary floor is £{sp.get('transitional_threshold_gbp', 31300):,} "
                      f"(or the job's lower going rate, if higher), not £{sp['general_threshold_gbp']:,}.")
        sw.details.insert(0, "gov.uk: the lower salary rules apply because your first certificate of sponsorship was before "
                             "4 April 2024 and you have held Skilled Worker visas continuously since. They cover applications "
                             "made before 4 April 2030.")
        sw.link = f"{GOV}/skilled-worker-visa/certificate-of-sponsorship-before-4-april-2024"
    if tr["medium_skilled"]:
        sw.details.insert(1 if tr["lower_salary"] else 0,
                          "gov.uk: because your first certificate was before 22 July 2025 (with continuous visas), you can update "
                          "your visa into a 'medium skilled' occupation. New applicants cannot. IT support roles are usually "
                          "coded 3131 (IT operations technicians) or 3132 (IT user support technicians): check the code your "
                          "employer would use in the table of eligible occupations.")
        sw.next_steps.append("Tell recruiters early: 'I'm already on a Skilled Worker visa, so you'd assign a new certificate of "
                             "sponsorship and I'd update my visa. I can keep working in my current job until it's approved.'")
        sw.next_steps.append("Do not start the new job until the updated visa is granted, and do not travel outside the UK "
                             "while the application is pending.")
    elif on_route and not v.first_cos_date:
        sw.details.insert(0, "You say you hold a Skilled Worker visa. Add visa.first_cos_date and continuous_since_first_cos to "
                             "your profile: if your first certificate was before 4 April 2024, your salary floor drops to "
                             f"£{sp.get('transitional_threshold_gbp', 31300):,}; before 22 July 2025, medium-skilled jobs such as "
                             "IT support are open to you.")
    sw.details += drift
    routes.append(sw)

    # ---- Scale-up
    routes.append(Route(
        "Scale-up Worker", "possible" if scaleup_count else "check",
        f"Sponsored by a fast-growing company for your first 6 months; after that you can change employer without "
        f"a new sponsor. Minimum £{sp.get('scaleup_threshold_gbp', 39100):,} or the going rate. The visa lasts 2 years "
        f"and counts towards settlement.",
        details=[f"{scaleup_count} employers currently hold a Scale-up licence. The agent searches their job boards "
                 f"and marks their jobs in your digest."] if scaleup_count else [],
        next_steps=["When a Scale-up sponsor makes an offer, ask them to sponsor you on the Scale-up route "
                    "rather than Skilled Worker: it gives you more freedom and costs them less."],
        link=f"{GOV}/scale-up-worker-visa/your-job"))

    # ---- HPI
    hpi = Route("High Potential Individual (HPI)", "check",
                "2 years of UK work rights (3 with a PhD) with no sponsor and no job offer needed.",
                link=f"{GOV}/high-potential-individual-visa/eligibility", needs_sponsor=False)
    gy = edu.graduation_year
    if edu.uk_degree:
        hpi.status, hpi.summary = "not_eligible", "UK universities aren't eligible for HPI."
    elif v.had_graduate_visa:
        hpi.status, hpi.summary = "not_eligible", "You can't apply for HPI if you've already had a Graduate visa."
    elif not edu.institution or not gy:
        hpi.details.append("Add education.institution and graduation_year to your profile to check this.")
    elif edu.highest_level not in ("bachelors", "masters", "phd"):
        hpi.status, hpi.summary = "unlikely", "HPI needs a bachelor's degree or higher."
    else:
        awarded = date(gy, edu.graduation_month or 7, 1)
        if (today - awarded).days > 5 * 365.25:
            hpi.status = "not_eligible"
            hpi.summary = f"HPI needs a qualification awarded in the last 5 years; yours was awarded in {gy}."
        else:
            # list year N covers 1 Nov N - 31 Oct N+1
            years = [gy if edu.graduation_month and edu.graduation_month >= 11 else gy - 1] if edu.graduation_month \
                else [gy - 1, gy]
            try:
                lists = hpi_lists(cache_dir)
                hits = hpi_match(edu.institution, lists, years)
                found = {y: h for y, h in hits.items() if h}
                if not lists:
                    hpi.details.append("Couldn't read the university lists from gov.uk. Check the link.")
                elif found and len(found) == len(years):
                    y, name = next(iter(found.items()))
                    hpi.status = "likely"
                    hpi.summary = (f"{name} is on the Home Office list for the year you graduated. You could get "
                                   f"2 years of UK work rights with no sponsor.")
                    hpi.next_steps = [
                        "Confirm the list for the exact month and year on your certificate (link below).",
                        "Get your degree verified by Ecctis, and check the English and savings requirements.",
                        "There's a yearly cap on HPI applications (the year runs 1 November to 31 October): apply early.",
                        "HPI can't be extended and doesn't count towards settlement, so use the 2 years to move to "
                        "Skilled Worker or Scale-up. Employers hire you like a local: no sponsor needed to start.",
                        "If you get it, set visa.needs_sponsorship: false and current_uk_right_to_work: true so the "
                        "agent stops filtering out employers that don't sponsor.",
                    ]
                elif found:
                    hpi.status = "possible"
                    hpi.summary = (f"{next(iter(found.values()))} is on the list for some award dates near yours. "
                                   f"Add education.graduation_month to your profile to be sure.")
                else:
                    hpi.status = "unlikely"
                    hpi.summary = (f"{edu.institution} isn't on the Home Office list for {', '.join(str(y) for y in years)} "
                                   f"(each list has roughly the world's top-ranked universities).")
            except Exception as e:
                hpi.details.append(f"Couldn't check the lists ({e.__class__.__name__}). Use the link.")
    routes.append(hpi)

    # ---- Graduate (only for courses studied on a Student visa)
    if edu.uk_degree:
        on_student = "student" in status_text
        if on_student:
            routes.append(Route(
                "Graduate visa", "likely",
                "2 years of work rights after a UK degree (3 after a PhD), no sponsor needed. You must apply from inside "
                "the UK while your Student visa is still valid.",
                next_steps=["Apply before your Student visa expires.",
                            "While you hold it, set visa.current_uk_right_to_work: true so employers see you can start now."],
                link=f"{GOV}/graduate-visa", needs_sponsor=False))
        else:
            routes.append(Route(
                "Graduate visa", "not_eligible",
                "Only for people who studied their UK degree on a Student visa. Your profile says you were on another "
                "visa, so this route doesn't apply.",
                link=f"{GOV}/graduate-visa/eligibility", needs_sponsor=False))

    # ---- nationality-based schemes
    nat = (v.nationality or "").strip()
    if nat:
        for slug, name in (("youth-mobility", "Youth Mobility Scheme"),
                           ("india-young-professionals-scheme-visa", "India Young Professionals Scheme")):
            try:
                text = " ".join(t for k, t in _guide(slug, cache_dir).items() if not k.startswith("_")).lower()
            except Exception:
                continue
            keys = [nat.lower()] + [k for k in COUNTRY_FORMS.get(nat.lower(), [])]
            if any(re.search(rf"\b{re.escape(k)}\b", text) for k in keys):
                routes.append(Route(
                    name, "possible",
                    f"gov.uk lists {nat} for this scheme: up to 2 years of work rights with no sponsor, with age "
                    f"limits and, for some countries, a ballot.",
                    next_steps=["Check the age range and whether your country uses a ballot (link below)."],
                    link=f"{GOV}/{slug}/eligibility", needs_sponsor=False))

    # ---- Global Talent (pointer)
    routes.append(Route(
        "Global Talent (digital technology)", "check",
        "For recognised or emerging leaders in tech: no sponsor, up to 5 years, and a faster path to settlement. "
        "It needs an endorsement based on evidence such as significant open-source work, publications, patents, "
        "founding or senior roles at product companies, or recognised awards.",
        next_steps=["Worth a look in a few years, or now if you have a strong public track record."],
        link=f"{GOV}/global-talent", needs_sponsor=False))
    return routes


# nationality adjective -> country names gov.uk uses
COUNTRY_FORMS = {
    "australian": ["australia"], "canadian": ["canada"], "new zealander": ["new zealand"], "japanese": ["japan"],
    "south korean": ["south korea", "republic of korea"], "korean": ["south korea", "republic of korea"],
    "taiwanese": ["taiwan"], "indian": ["india", "indian"], "icelandic": ["iceland"], "uruguayan": ["uruguay"],
    "hong kong": ["hong kong"], "monegasque": ["monaco"], "andorran": ["andorra"], "sammarinese": ["san marino"],
}

def insights_for(routes: list[Route]) -> list[tuple[int, str, str]]:
    """(priority, title, detail) for the digest: only things you can act on."""
    out = []
    for r in routes:
        if r.name.startswith("High Potential") and r.status in ("likely", "possible"):
            out.append((1, "You may not need a sponsor at all (HPI visa)",
                        r.summary + " Run `jobstream visa` for the steps."))
        if r.name == "Skilled Worker":
            for d in r.details:
                if d.startswith("You say you hold a Skilled Worker visa"):
                    out.append((1, "Your salary floor may be £31,300, not £41,700", d))
                if d.startswith("New-entrant rate") and r.next_steps:
                    out.append((1, "You may qualify for the lower new-entrant salary", d + " " + r.next_steps[0]))
                if d.startswith("gov.uk now says"):
                    out.append((1, "A visa salary threshold has changed", d))
        if r.name in ("Youth Mobility Scheme", "India Young Professionals Scheme"):
            out.append((2, f"{r.name} may be open to you", r.summary + " Run `jobstream visa`."))
    return out


LABEL = {"likely": "LIKELY", "possible": "POSSIBLE", "unlikely": "UNLIKELY", "not_eligible": "NOT ELIGIBLE",
         "check": "WORTH CHECKING"}


def report_markdown(routes: list[Route]) -> str:
    out = ["# Your visa routes", "",
           "Checked against gov.uk. This is a pointer to the right pages, not immigration advice.", ""]
    for r in routes:
        out += [f"## {r.name}: {LABEL[r.status]}" + ("" if r.needs_sponsor else " (no sponsor needed)"), "", r.summary, ""]
        out += [f"- {d}" for d in r.details]
        if r.next_steps:
            out += ["", "Next steps:"] + [f"- {s}" for s in r.next_steps]
        out += ["", f"Source: {r.link}", ""]
    return "\n".join(out)
