"""Fast, explainable scoring of a job against the profile (no LLM needed).

Score is 0-100. Every point can be traced to a component, so the digest can
tell you *why* a job ranked where it did.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .models import Job, Profile, ScoreBreakdown
from .skills import canonical, extract_weighted
from .sponsors import Sponsor
from .visa import clearance_required, salary_check, sponsorship_signal

WEIGHTS = {"skills": 35, "title": 20, "seniority": 10, "location": 10, "salary": 10, "sponsorship": 10, "freshness": 5}

LEVELS = ["intern", "graduate", "junior", "mid", "senior", "staff", "lead", "principal"]
LEVEL_PATTERNS = [
    ("intern", r"\bintern(ship)?\b|\bplacement\b"),
    ("graduate", r"\bgraduate\b|\bgrad\b|\bentry[- ]level\b|\bearly careers?\b"),
    ("junior", r"\bjunior\b|\bjr\.?\b|\bassociate\b"),
    ("principal", r"\bprincipal\b|\bdistinguished\b|\bhead of\b|\bdirector\b"),
    ("staff", r"\bstaff\b"),
    ("lead", r"\blead\b|\bmanager\b|\btech lead\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b|\bsnr\b"),
    ("mid", r"\bmid[- ]?(level|weight)?\b|\bintermediate\b|\b(engineer|developer) ii\b"),
]
TITLE_SYNONYMS = [
    (r"\bdeveloper\b|\bprogrammer\b|\bswe\b", "engineer"),
    (r"\bback[- ]end\b", "backend"),
    (r"\bfront[- ]end\b", "frontend"),
    (r"\bfull[- ]?stack\b", "fullstack"),
    (r"\bml\b", "machine learning"),
    (r"\brse\b", "research software engineer"),
    (r"\bbusiness intelligence\b", "bi"),
    (r"\bsre\b", "site reliability"),
    (r"\bdev ?ops\b", "devops"),
]
STOP = {"the", "a", "an", "of", "and", "&", "in", "for", "with", "to", "-", "/", "i", "ii", "iii"}


def _title_tokens(title: str) -> set[str]:
    t = (title or "").lower()
    for pat, rep in TITLE_SYNONYMS:
        t = re.sub(pat, rep, t)
    for _, pat in LEVEL_PATTERNS:
        t = re.sub(pat, " ", t)
    t = re.sub(r"\(.*?\)|[^a-z0-9+# ]", " ", t)
    return {w for w in t.split() if w not in STOP}


def detect_level(title: str) -> Optional[str]:
    for level, pat in LEVEL_PATTERNS:
        if re.search(pat, title or "", re.I):
            return level
    return None


def required_years(text: str) -> Optional[int]:
    hits = [int(m.group(1)) for m in re.finditer(r"(\d{1,2})\s?\+?\s?(?:-\s?\d+\s)?years?", text or "", re.I)]
    hits = [h for h in hits if 0 < h < 20]
    return min(hits) if hits else None


def score_title(job: Job, profile: Profile) -> float:
    jt = _title_tokens(job.title)
    if not jt:
        return 0.0
    best = 0.0
    for rank, role in enumerate(profile.targets.roles):
        rt = _title_tokens(role)
        if not rt:
            continue
        overlap = len(jt & rt) / len(rt)
        if "engineer" in rt and "engineer" not in jt:
            overlap *= 0.5  # "Data Engineer" target vs "Data Scientist" advert
        # rank decay: first target role counts most
        best = max(best, overlap * (1 - 0.05 * min(rank, 6)))
    # Titles naming one of your strong skills ("Python Engineer") are good signs
    strong = {s.name.lower() for s in profile.skills if s.level >= 3}
    if jt & strong and "engineer" in jt:
        best = max(best, 0.8)
    return min(best, 1.0)


def score_seniority(job: Job, profile: Profile) -> tuple[float, list[str]]:
    notes = []
    level = detect_level(job.title)
    wanted = [l.lower() for l in profile.targets.seniority]
    score = 0.7 if level is None else 0.0
    if level and level in wanted:
        score = 1.0
    elif level and wanted:
        dist = min(abs(LEVELS.index(level) - LEVELS.index(w)) for w in wanted if w in LEVELS)
        score = {1: 0.5, 2: 0.15}.get(dist, 0.0)
        notes.append(f"Title level '{level}' vs your target {wanted}")
    yrs = required_years(job.description)
    if yrs is not None:
        have = profile.targets.years_experience
        if have + 1 < yrs:
            score *= 0.5
            notes.append(f"Asks for {yrs}+ years; you have {have:g}")
        elif have >= yrs and level is None:
            score = max(score, 0.8)
    return score, notes


def score_location(job: Job, profile: Profile) -> float:
    loc = (job.location or "").lower()
    if job.remote == "remote" or "remote" in loc:
        return 1.0 if profile.targets.remote_ok else 0.3
    for target in profile.targets.locations:
        city = target.lower().split("(")[0].strip()
        if city and city != "remote" and city in loc:
            return 1.0
    return 0.6 if profile.visa.willing_to_relocate else 0.2


def score_freshness(job: Job) -> float:
    if not job.posted_at:
        return 0.5
    posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - posted).days
    if days <= 7:
        return 1.0
    if days <= 14:
        return 0.7
    if days <= 30:
        return 0.4
    return 0.1


def score_job(job: Job, profile: Profile, settings: dict, sponsor: Optional[Sponsor],
              weights: Optional[dict] = None, scaleup: Optional[Sponsor] = None) -> ScoreBreakdown:
    """`weights` defaults to WEIGHTS; learn.py supplies tuned ones once you have results."""
    blockers: list[str] = []
    notes: list[str] = []
    text = f"{job.title}\n{job.description}"

    # ---- hard filters
    tl = job.title.lower()
    for w in profile.targets.exclude_title_words:
        if re.search(rf"\b{re.escape(w.lower())}\b", tl):
            blockers.append(f"Title contains excluded word '{w}'")
    if any(c.lower() == job.company.lower() for c in profile.targets.exclude_companies):
        blockers.append("Company is on your exclude list")

    # ---- skills
    jd = extract_weighted(text)
    mine = {canonical(s.name): s for s in profile.skills}
    if jd:
        total_w = sum(jd.values())
        got = 0.0
        for sk, w in jd.items():
            if sk in mine:
                got += w * (0.6 + 0.1 * min(mine[sk].level, 4))
        skills = min(got / total_w, 1.0)
    else:
        skills = 0.4
        notes.append("Advert lists no recognisable tech skills")
    matched = sorted(k for k in jd if k in mine)
    missing = sorted((k for k in jd if k not in mine), key=lambda k: -jd[k])

    title = score_title(job, profile)
    seniority, sen_notes = score_seniority(job, profile)
    notes += sen_notes
    location = score_location(job, profile)
    freshness = score_freshness(job)

    # ---- salary vs visa rules and your minimum
    sc = salary_check(job.salary_min, job.salary_max, settings, profile.visa)
    if sc.status == "ok":
        salary = 1.0
        top = job.salary_max or job.salary_min or 0
        if profile.targets.min_salary_gbp and top < profile.targets.min_salary_gbp:
            salary = 0.4
            notes.append(f"Below your minimum salary of £{profile.targets.min_salary_gbp:,}")
    elif sc.status == "below":
        salary = 0.0
        su_min = settings["sponsorship"].get("scaleup_threshold_gbp", 39100)
        top = job.salary_max or job.salary_min or 0
        if scaleup and top >= su_min:
            salary = 0.7
            notes.append(f"Below the Skilled Worker minimum but meets the £{su_min:,} Scale-up minimum")
        elif profile.visa.needs_sponsorship:
            blockers.append(sc.detail)
    else:
        salary = 0.5
    notes.append(sc.detail)

    # ---- sponsorship
    sig = sponsorship_signal(job.description)
    if profile.visa.needs_sponsorship:
        if sig.label == "negative":
            blockers.append("Advert says no visa sponsorship: " + sig.evidence[0][:120])
            sponsorship = 0.0
        elif (sponsor or scaleup) and sig.label == "positive":
            sponsorship = 1.0
        elif sponsor or scaleup:
            sponsorship = 0.75 if (sponsor or scaleup).a_rated else 0.55
            if sig.label == "weak_negative":
                sponsorship -= 0.25
                notes.append("Advert mentions right to work. Ask the recruiter whether they sponsor for this role.")
        elif sig.label == "positive":
            sponsorship = 0.6
            notes.append("Advert offers sponsorship but the employer name is not on the register (agency or different legal name?)")
        else:
            sponsorship = 0.0
            if settings["sponsorship"]["require_licensed_sponsor"]:
                blockers.append("Employer not found on the Skilled Worker sponsor register")
        if profile.visa.skip_security_clearance_roles:
            clr = clearance_required(text)
            if clr:
                blockers.append("Security clearance needed: " + clr[0][:100])
    else:
        sponsorship = 1.0

    parts = {
        "skills": skills, "title": title, "seniority": seniority, "location": location,
        "salary": salary, "sponsorship": max(sponsorship, 0.0), "freshness": freshness,
    }
    w = weights or WEIGHTS
    total = sum(w.get(k, WEIGHTS[k]) * v for k, v in parts.items())
    if scaleup and profile.visa.needs_sponsorship:
        total += 3
        notes.append("Licensed Scale-up sponsor: on a Scale-up visa you only have to stay with the sponsor for "
                     "6 months, then you can change jobs without a new sponsor. Ask them which route they'd use.")
    if any(d.lower() == job.company.lower() for d in profile.targets.dream_companies):
        total += 5
        notes.append("Dream company")
    if title < 0.3:
        total *= 0.6  # wrong kind of role, however good the rest looks
    if seniority < 0.2:
        total *= 0.75  # two or more levels away from what you are aiming for
    if blockers:
        total = min(total, 20)
    return ScoreBreakdown(
        total=round(min(total, 100), 1), **{k: round(v, 2) for k, v in parts.items()},
        matched_skills=matched, missing_skills=missing[:12], blockers=blockers, notes=notes,
        scaleup=bool(scaleup),
    )


TECH_DOMAINS = {"software", "backend", "frontend", "fullstack", "data", "platform", "devops", "cloud",
                "machine", "infrastructure", "site", "api", "web", "mobile", "ios", "android", "ai", "python",
                # common in the NHS, universities, councils, banks...
                "systems", "system", "application", "applications", "digital", "it", "integration", "database",
                "informatics", "research", "bi", "intelligence", "solutions", "technical", "technology"}


def quick_title_filter(profile: Profile):
    """A cheap check on the title alone, used before fetching full adverts."""
    excl = [re.compile(rf"\b{re.escape(w.lower())}\b") for w in profile.targets.exclude_title_words]
    cores = [_title_tokens(r) - {"engineer"} for r in profile.targets.roles]
    skills = {s.name.lower() for s in profile.skills}

    def want(title: str) -> bool:
        if any(p.search((title or "").lower()) for p in excl):
            return False
        tt = _title_tokens(title)
        if any(tt & core for core in cores) or tt & skills:
            return True
        return "engineer" in tt and bool(tt & TECH_DOMAINS)

    return want
