"""Who to talk to: contacts, LinkedIn/Google searches, email patterns and outreach messages.

Nothing here scrapes LinkedIn (that breaks its terms and gets accounts banned).
Instead we build precise search links you open yourself, read names and emails
that the advert itself publishes, and optionally use Hunter.io's API.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

from .config import Context
from .http import get_json
from .llm import LLM
from .models import Job, OutreachMessage, OutreachPlan
from .prompts import OUTREACH_TASK, job_block, system_prompt

ATS_DOMAINS = ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "workable.com", "reed.co.uk",
               "adzuna", "linkedin.com", "glassdoor", "indeed", "google.com", "gov.uk", "youtube.com",
               "twitter.com", "x.com", "facebook.com", "instagram.com", "medium.com", "bit.ly")


@dataclass
class Contact:
    name: str = ""
    role: str = ""
    email: str = ""
    email_confidence: str = ""     # published | verified | pattern-guess
    linkedin: str = ""
    source: str = ""


@dataclass
class NetworkPlan:
    company: str
    domain: Optional[str]
    contacts: list[Contact] = field(default_factory=list)
    search_links: list[tuple[str, str]] = field(default_factory=list)   # (label, url)
    email_patterns: list[str] = field(default_factory=list)
    outreach: Optional[OutreachPlan] = None


# ---------------------------------------------------------------------------- domain
def company_domain(job: Job) -> Optional[str]:
    """Best guess at the employer's website domain."""
    urls = re.findall(r"https?://(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})", job.description or "", re.I)
    emails = re.findall(r"[\w.+-]+@([a-z0-9.-]+\.[a-z]{2,})", job.description or "", re.I)
    counts = Counter(d.lower() for d in urls + emails if not any(a in d.lower() for a in ATS_DOMAINS))
    name_key = re.sub(r"[^a-z0-9]", "", job.company.lower())
    for dom, _ in counts.most_common():
        if name_key[:5] and name_key[:5] in dom.replace("-", ""):
            return dom
    try:  # free company-name -> domain lookup
        res = get_json("https://autocomplete.clearbit.com/v1/companies/suggest",
                       params={"query": job.company}, timeout=10) or []
        for r in res:
            if re.sub(r"[^a-z0-9]", "", r.get("name", "").lower()) == name_key:
                return r["domain"]
        if res:
            return res[0]["domain"]
    except Exception:
        pass
    return counts.most_common(1)[0][0] if counts else None


# ---------------------------------------------------------------------------- contacts from the advert
_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z'\-]+){1,2})"


def contacts_in_advert(job: Job) -> list[Contact]:
    text = job.description or ""
    found: list[Contact] = []
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        email = m.group(0).rstrip(".")
        if any(x in email.lower() for x in ("noreply", "no-reply", "privacy", "gdpr", "dataprotection", "accommodation")):
            continue
        found.append(Contact(email=email, email_confidence="published", source="advert"))
    for pat, role in [
        (rf"(?:reach out to|contact|email|speak to|message)\s+{_NAME}", "Named in advert"),
        (rf"{_NAME},?\s+(?:our|the)\s+(?:hiring manager|engineering manager|head of [a-z]+|recruiter|talent partner|cto)", "Hiring contact"),
        (rf"(?:hiring manager|you(?:'|’)ll report to|reporting to)\s*(?:is|:)?\s+{_NAME}", "Hiring manager"),
    ]:
        for m in re.finditer(pat, text):
            found.append(Contact(name=m.group(1), role=role, source="advert"))
    return found


# ---------------------------------------------------------------------------- search links
def search_links(job: Job, people_titles: list[str], location: str = "United Kingdom") -> list[tuple[str, str]]:
    c = job.company
    links = []
    for title in people_titles:
        q = f'"{c}" {title}'
        links.append((f"LinkedIn: {title} at {c}",
                      f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(q)}&origin=GLOBAL_SEARCH_HEADER"))
    links.append((f"Google X-ray: {c} engineering managers in the UK",
                  "https://www.google.com/search?q=" + quote_plus(f'site:linkedin.com/in "{c}" ("engineering manager" OR "head of engineering") "{location}"')))
    links.append((f"Google X-ray: {c} recruiters",
                  "https://www.google.com/search?q=" + quote_plus(f'site:linkedin.com/in "{c}" ("technical recruiter" OR "talent acquisition" OR "talent partner")')))
    links.append((f"Google: people who moved to {c} on a visa",
                  "https://www.google.com/search?q=" + quote_plus(f'site:linkedin.com/in "{c}" ("skilled worker visa" OR "relocated to London" OR "moved to the UK")')))
    links.append((f"LinkedIn: {c} company page (People tab, filter by your school)",
                  f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(c)}"))
    links.append((f"Glassdoor interviews at {c}",
                  "https://www.google.com/search?q=" + quote_plus(f'{c} software engineer interview questions glassdoor')))
    links.append((f"{c} engineering blog / GitHub",
                  "https://www.google.com/search?q=" + quote_plus(f'{c} engineering blog OR github.com/{re.sub("[^a-z0-9]", "", c.lower())}')))
    return links


def email_patterns(domain: Optional[str]) -> list[str]:
    if not domain:
        return []
    return [f"{p}@{domain}" for p in ("first.last", "first", "firstlast", "f.last", "flast")]


# ---------------------------------------------------------------------------- Hunter.io (optional)
def hunter_contacts(domain: str, limit: int = 10) -> list[Contact]:
    key = os.environ.get("HUNTER_API_KEY")
    if not key or not domain:
        return []
    data = get_json("https://api.hunter.io/v2/domain-search",
                    params={"domain": domain, "limit": limit, "department": "it,management,hr", "api_key": key}) or {}
    out = []
    for e in (data.get("data") or {}).get("emails", []):
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        out.append(Contact(name=name, role=e.get("position") or e.get("department") or "", email=e.get("value", ""),
                           email_confidence=f"hunter {e.get('confidence', '?')}%", linkedin=e.get("linkedin") or "",
                           source="hunter.io"))
    pattern = (data.get("data") or {}).get("pattern")
    if pattern:
        out.append(Contact(role="Email pattern", email=f"{pattern}@{domain}", email_confidence="hunter pattern",
                           source="hunter.io"))
    return out


# ---------------------------------------------------------------------------- outreach
def template_outreach(ctx: Context, job: Job) -> OutreachPlan:
    me = ctx.profile.personal.first_name
    proof = ctx.cv.experience[0].bullets[0].text if ctx.cv.experience and ctx.cv.experience[0].bullets else ""
    msgs = [
        OutreachMessage(channel="linkedin_connection", target="Hiring manager", subject="", send_on="day 0",
                        body=f"Hi [First name], I've just applied for the {job.title} role on your team. "
                             f"I've been {proof[:120].lower()}, and would love to hear what the team is focused on. {me}"),
        OutreachMessage(channel="linkedin_message", target="Recruiter", subject="", send_on="day 0",
                        body=f"Hi [First name], I applied for {job.title} at {job.company} today. "
                             f"Quick highlight: {proof}. Could you confirm whether the role is open to candidates who "
                             f"need {ctx.profile.visa.target_route} sponsorship? Happy to share anything that helps. Thanks, {me}"),
        OutreachMessage(channel="follow_up_email", target="Recruiter", subject=f"{job.title} application: {ctx.profile.personal.full_name}",
                        send_on="day 6",
                        body=f"Hi [First name],\n\nI applied for the {job.title} role last week and wanted to check in. "
                             f"I'm still very keen; {proof}. Is there anything else I can send to help?\n\nBest,\n{ctx.profile.personal.full_name}"),
    ]
    return OutreachPlan(people_to_find=["Engineering Manager", "Senior Software Engineer", "Technical Recruiter"],
                        messages=msgs, tips=["Comment thoughtfully on a recent post by the hiring manager before messaging."])


def outreach_plan(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None) -> OutreachPlan:
    if llm is None:
        return template_outreach(ctx, job)
    return llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, "a well-connected UK tech networking coach"),
        prompt=job_block(job, sponsor) + "\n" + OUTREACH_TASK.format(company=job.company, spelling=ctx.profile.writing.spelling),
        schema=OutreachPlan, effort="medium",
    )


def build_plan(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None) -> NetworkPlan:
    domain = company_domain(job)
    outreach = outreach_plan(llm, ctx, job, sponsor)
    contacts = contacts_in_advert(job)
    try:
        contacts += hunter_contacts(domain) if domain else []
    except Exception:
        pass
    return NetworkPlan(
        company=job.company, domain=domain, contacts=contacts,
        search_links=search_links(job, outreach.people_to_find[:4]),
        email_patterns=email_patterns(domain), outreach=outreach,
    )


def plan_markdown(plan: NetworkPlan) -> str:
    out = [f"# Networking plan: {plan.company}", ""]
    if plan.domain:
        out += [f"Company domain: `{plan.domain}`", ""]
    out += ["## People to find"]
    for t in (plan.outreach.people_to_find if plan.outreach else []):
        out.append(f"- {t}")
    out += ["", "## Search links (open these yourself, logged in to LinkedIn)"]
    out += [f"- [{label}]({url})" for label, url in plan.search_links]
    if plan.contacts:
        out += ["", "## Contacts found", "| Name | Role | Email | Confidence | Source |", "|---|---|---|---|---|"]
        out += [f"| {c.name} | {c.role} | {c.email} | {c.email_confidence} | {c.source} |" for c in plan.contacts]
    if plan.email_patterns:
        out += ["", "## Likely email formats (guesses: check them with a verifier before sending)"]
        out += [f"- `{p}`" for p in plan.email_patterns]
    if plan.outreach:
        out += ["", "## Messages"]
        for m in plan.outreach.messages:
            out += ["", f"### {m.channel.replace('_', ' ').title()} to {m.target} ({m.send_on})"]
            if m.subject:
                out.append(f"**Subject:** {m.subject}")
            out += ["", m.body]
        if plan.outreach.tips:
            out += ["", "## Tips"] + [f"- {t}" for t in plan.outreach.tips]
    return "\n".join(out) + "\n"
