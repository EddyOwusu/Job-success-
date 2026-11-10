"""Rule-based answers to common application-form fields (used for known fields, and when Claude is off)."""
from __future__ import annotations

import re
from typing import Optional

from ..config import Context
from ..models import FormAnswer, FormAnswers

# (regex on the label, key) - the order matters, first hit wins
KNOWN_FIELDS: list[tuple[str, str]] = [
    (r"^\s*first\s*name|given name|forename", "first_name"),
    (r"^\s*(last|family)\s*name|surname", "last_name"),
    (r"^\s*(full\s*)?name\s*\*?\s*$|your name|legal name", "full_name"),
    (r"preferred name", "first_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|telephone", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"website|portfolio|personal (site|url)|other (link|url)", "portfolio"),
    (r"^\s*(current )?(location|city)|where are you (based|located)|city of residence", "location"),
    (r"current (company|employer)|^\s*(company|organi[sz]ation)\s*\*?\s*$", "current_company"),
    (r"current (job )?title|current role", "current_title"),
    (r"(require|need).{0,40}(sponsor|visa)|sponsorship", "needs_sponsorship"),
    (r"(right|authori[sz]ed|eligible|legally).{0,30}work.{0,30}(uk|united kingdom|country)", "right_to_work"),
    (r"notice period|when can you start|earliest start|start date|availability", "notice_period"),
    (r"salary|compensation|pay expectation", "salary_expectation"),
    (r"how did you (hear|find)|where did you (hear|find|see)|referr(al|ed) source", "how_did_you_hear"),
    (r"relocat", "willing_to_relocate"),
    (r"pronoun", "pronouns"),
    (r"gender|sex\b", "gender"),
    (r"ethnic|race", "ethnicity"),
    (r"disab", "disability"),
    (r"veteran|armed forces", "veteran"),
    (r"us person|u\.s\. person", "us_person"),
    (r"(over|at least) (the age of )?18|18 years", "over_18"),
    (r"nationality|citizenship", "nationality"),
    (r"current (visa|immigration) status|visa status", "visa_status"),
]


def clean_label(label: str) -> str:
    label = re.sub(r"[✱*]+|\(required\)|\brequired\b", " ", label or "", flags=re.I)
    return re.sub(r"\s+", " ", label).strip()


def classify(label: str) -> Optional[str]:
    label = clean_label(label)
    for pat, key in KNOWN_FIELDS:
        if re.search(pat, label, re.I):
            return key
    return None


def value_for(key: str, ctx: Context) -> Optional[str]:
    p, v, sa = ctx.profile.personal, ctx.profile.visa, ctx.profile.standard_answers
    current = ctx.cv.experience[0] if ctx.cv.experience else None
    values = {
        "first_name": p.first_name, "last_name": p.last_name, "full_name": p.full_name,
        "email": p.email, "phone": p.phone, "linkedin": p.linkedin, "github": p.github,
        "portfolio": p.portfolio or p.github, "location": p.location, "pronouns": p.pronouns,
        "current_company": current.company if current and current.end.lower() == "present" else "",
        "current_title": current.title if current and current.end.lower() == "present" else "",
        "needs_sponsorship": "Yes" if v.needs_sponsorship else "No",
        "right_to_work": "Yes" if (v.current_uk_right_to_work or not v.needs_sponsorship) else "No",
        "willing_to_relocate": "Yes" if v.willing_to_relocate else "No",
        "nationality": v.nationality, "visa_status": v.current_status,
    }
    if key in values and values[key]:
        return values[key]
    return sa.get(key) or None


def pick_option(answer: str, options: list[str]) -> Optional[str]:
    """Choose the option that best matches a free-text answer."""
    if not options:
        return answer
    a = answer.strip().lower()
    for o in options:
        if o.strip().lower() == a:
            return o
    for o in options:
        ol = o.lower()
        if a in ol or ol in a:
            return o
    if a in ("yes", "no"):
        for o in options:
            if o.lower().startswith(a):
                return o
    if "prefer not" in a or "decline" in a:
        for o in options:
            if re.search(r"prefer not|decline|don.t wish|do not wish|rather not", o, re.I):
                return o
    return None


def rule_based_answers(ctx: Context, questions: list[dict]) -> FormAnswers:
    out = []
    for q in questions:
        key = classify(q["label"])
        val = value_for(key, ctx) if key else None
        if val and q.get("options"):
            val = pick_option(val, q["options"])
        out.append(FormAnswer(question=q["label"], answer=val or "", confidence="high" if val else "low",
                              needs_human=not val and bool(q.get("required"))))
    return FormAnswers(answers=out)
