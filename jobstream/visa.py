"""Visa checks on an advert: what it says about sponsorship, clearance blockers, salary rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

POSITIVE = [
    r"visa sponsorship (is )?(available|offered|provided|possible)",
    r"(we|we're|we are|we can|we will|we do|happy to|able to|willing to|can) (offer |provide |consider )?(visa )?sponsor",
    r"sponsorship (is )?(available|offered|provided|considered|possible)",
    r"skilled worker (visa|sponsorship|route)",
    r"(offer|provide|support)( with)? (visa|immigration) (sponsorship|support)",
    r"relocation (and|&) visa",
    r"visa support",
    r"tier 2",
    r"certificate of sponsorship",
    r"open to (candidates|applicants) (who )?(require|need)(ing)? (visa )?sponsorship",
    # NHS standard wording
    r"(require|need)s? (current )?skilled worker sponsorship[^.]{0,80}(are|is) welcome",
    r"eligible for (visa |skilled worker )?sponsorship",
]
_NOT = r"(unable|not able|cannot|can['’]t|can not|won['’]t|will not|do not|don['’]t|does not|doesn['’]t|are not able|aren['’]t able|not possible|not in a position)"
NEGATIVE = [
    _NOT + r"\b[^.,;\n]{0,60}\bsponsor",
    r"no (visa )?sponsorship",
    r"sponsorship (is |will )?(not |un)(available|offered|possible|be (offered|provided))",
    r"not (eligible|open) (for|to) (visa )?sponsorship",
    r"not (offer|provide)(ing)? (visa )?sponsorship",
    r"without (the need for |requiring )?(visa )?sponsorship",
    r"(require|need)s? no (visa )?sponsorship",
    r"(british|uk) (citizen|national)s? only",
    r"must be (a )?(british|uk) (citizen|national)",
    r"settled status (is )?required",
]
HEDGE = re.compile(r"\bevery (role|candidate|position|case)|\ball (roles|candidates|positions|cases)\b|"
                   r"\bin (some|all) cases\b|\bguarantee", re.I)
# Weaker: often boilerplate, and overridden if the advert also says it sponsors
WEAK_NEGATIVE = [
    r"must (already )?have (the |an existing |existing |full |unrestricted )?right to work",
    r"(applicants|candidates) must be (eligible|authori[sz]ed) to work in the uk",
]
CLEARANCE = [
    r"\bsc\s*(clearance|cleared)\b", r"\bdv\s*(clearance|cleared)\b", r"security clearance",
    r"\bnpp?v\d?\b", r"\bbpss\b(?! and)", r"eligible (for|to obtain) (sc|dv|security)",
    r"\bctc clearance\b", r"developed vetting",
]


@dataclass
class SponsorshipSignal:
    label: str                      # positive | negative | weak_negative | neutral
    evidence: list[str] = field(default_factory=list)


def _find(patterns: list[str], text: str) -> list[str]:
    hits = []
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            s, e = max(0, m.start() - 60), min(len(text), m.end() + 60)
            hits.append(text[s:e].replace("\n", " ").strip())
    return hits


def sponsorship_signal(text: str) -> SponsorshipSignal:
    text = text or ""
    # "We do sponsor visas! However, we aren't able to sponsor visas for every role and every candidate"
    # is a hedge, not a refusal
    neg = [n for n in _find(NEGATIVE, text) if not HEDGE.search(n)]
    pos = _find(POSITIVE, text)
    weak = _find(WEAK_NEGATIVE, text)
    # "we are unable to sponsor" contains "to sponsor", so explicit negatives win
    if neg:
        return SponsorshipSignal("negative", neg)
    if pos:
        return SponsorshipSignal("positive", pos)
    if weak:
        return SponsorshipSignal("weak_negative", weak)
    return SponsorshipSignal("neutral", [])


def clearance_required(text: str) -> list[str]:
    return _find(CLEARANCE, text or "")


# ---------------------------------------------------------------------- salary
_MONEY = r"£\s?(\d{2,3}(?:,\d{3})|\d{2,3}(?:\.\d)?\s?[kK]|\d{4,6})"


def _to_number(raw: str) -> float:
    raw = raw.replace(",", "").replace(" ", "")
    if raw.lower().endswith("k"):
        return float(raw[:-1]) * 1000
    return float(raw)


def parse_salary(text: str) -> tuple[Optional[float], Optional[float]]:
    """Find an annual GBP salary range in free text, e.g. '£45,000 - £60,000' or '£50k-£65k'."""
    if not text:
        return None, None
    rng = re.search(_MONEY + r"\s?(?:-|–|—|to)\s?" + _MONEY, text)
    if rng:
        lo, hi = _to_number(rng.group(1)), _to_number(rng.group(2))
    else:
        one = re.search(_MONEY + r"(?!\s?(?:per|an|/)\s?(?:hour|day|hr))", text)
        if not one:
            return None, None
        lo = hi = _to_number(one.group(1))
    # Ignore day rates / hourly rates
    if hi < 15000:
        return None, None
    return lo, hi


@dataclass
class SalaryCheck:
    status: str          # ok | below | unknown
    detail: str


def salary_check(salary_min: Optional[float], salary_max: Optional[float], settings: dict, new_entrant: bool) -> SalaryCheck:
    sp = settings["sponsorship"]
    threshold = sp["new_entrant_threshold_gbp"] if new_entrant else sp["general_threshold_gbp"]
    if not salary_min and not salary_max:
        return SalaryCheck("unknown", f"Salary not stated. Ask the recruiter if it is at least £{threshold:,.0f}.")
    top = salary_max or salary_min
    bottom = salary_min or salary_max
    if bottom >= threshold:
        return SalaryCheck("ok", f"£{bottom:,.0f}+ meets the £{threshold:,.0f} Skilled Worker threshold.")
    if top >= threshold:
        return SalaryCheck("ok", f"Range £{bottom:,.0f}-£{top:,.0f}: you need an offer of at least £{threshold:,.0f}.")
    return SalaryCheck("below", f"Top of range £{top:,.0f} is below the £{threshold:,.0f} Skilled Worker threshold.")
