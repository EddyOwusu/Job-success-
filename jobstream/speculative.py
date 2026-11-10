"""Speculative approaches: contact licensed sponsors that fit you but have no matching vacancy.

Many UK roles are filled before they are advertised, and a sponsor that already holds a
licence can hire you without the months of paperwork a new sponsor needs. This module
ranks such employers, explains why each is worth approaching, and drafts a short,
specific note for a named kind of person plus a CV aimed at that company's stack.

It never sends anything. You send the messages yourself, a few per week.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from . import networking, render
from .config import OUTPUT_DIR, Context
from .db import DB, now_iso
from .discovery import TECH_HUBS
from .llm import LLM, LLMError
from .models import Job
from .prompts import system_prompt
from .skills import canonical, extract_skills
from .sponsors import SponsorRegister
from .tailor import keyword_tailor, tailor_cv
from .text import slug
from .visa import sponsorship_signal

ACTIVE = ("shortlisted", "packed", "applied", "interview", "offer")


@dataclass
class Target:
    company: str
    sponsor_name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)        # their tech that you also have
    their_stack: list[str] = field(default_factory=list)  # everything they mention
    roles_hiring: list[str] = field(default_factory=list)
    scaleup: bool = False
    new_sponsor: bool = False
    url: str = ""


class SpeculativeApproach(BaseModel):
    why_them: list[str] = Field(description="2-4 specific reasons this company fits the candidate")
    value_pitch: list[str] = Field(description="2-3 concrete things the candidate could do for them, tied to their product or stack")
    people_to_find: list[str] = Field(description="Job titles to contact, most useful first")
    linkedin_note: str = Field(description="Connection note, at most 280 characters")
    email_subject: str
    email_body: str = Field(description="About 120 words: specific hook, one piece of evidence, the ask, one line on sponsorship")
    follow_up: str = Field(description="About 50 words, to send after 7 days of silence")
    tips: list[str]


SPEC_TASK = """The candidate wants to approach this employer speculatively: there is no suitable vacancy
advertised right now, but the employer is a licensed UK visa sponsor and its work matches the
candidate's skills.

Employer: {company}
Registered sponsor name: {sponsor}{scaleup}
Technology it uses that the candidate also has: {stack}
Other technology in its adverts: {their_stack}
Roles it has advertised recently: {roles}

Research notes (from web search; trust them over your own memory, and don't invent facts
that aren't here or in the adverts):
<research>
{research}
</research>

Write the approach:
- why_them and value_pitch must be specific to this employer. If you know too little to be
  specific, say what the candidate should look up first rather than writing something generic.
- people_to_find: the likely hiring manager for a team the candidate would join, an engineer on
  that team, and a recruiter or talent partner.
- linkedin_note, email and follow_up: short, human, in {spelling}. Lead with something about
  them, not the candidate. One piece of hard evidence from the dossier. A small, easy ask
  ("a 15-minute chat", "who's the right person?"), never "please give me a job". Use [First name]
  for names. One calm line on sponsorship in the email: the company already holds a sponsor
  licence, and the candidate would need {route} sponsorship.
- tips: 3-4 ways to warm up the approach first (their blog, an open-source repo, a meetup,
  a recent launch to reference).
"""


# ---------------------------------------------------------------------------- ranking
def _recent(db: DB, days: int) -> set[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.conn.execute("SELECT lower(company) FROM speculative WHERE created_at>=? OR status IN ('sent','replied')", (since,))
    return {r[0] for r in rows}


def targets(db: DB, ctx: Context, register: SponsorRegister, limit: int = 15) -> list[Target]:
    """Licensed sponsors worth a speculative approach, best first."""
    p = ctx.profile
    mine = {canonical(s.name) for s in p.skills}
    excluded = {c.lower() for c in p.targets.exclude_companies}
    dream = {c.lower() for c in p.targets.dream_companies}
    approached = _recent(db, 90)
    new_names = {r[0] for r in db.conn.execute(
        "SELECT name FROM sponsor_seen WHERE baseline=0 AND first_seen>=?",
        ((date.today() - timedelta(days=30)).isoformat(),))}

    by_company: dict[str, list] = {}
    for r in db.conn.execute("SELECT * FROM jobs"):
        by_company.setdefault(r["company"], []).append(r)

    out: list[Target] = []
    for company, rows in by_company.items():
        key = company.lower()
        if key in excluded or key in approached:
            continue
        if any(r["status"] in ACTIVE for r in rows):
            continue                       # there's a real vacancy in play: apply to that instead
        if any(json.loads(r["extra"] or "{}").get("sector") in ("nhs", "university") for r in rows):
            continue                       # public bodies must hire through advertised vacancies
        sp = register.match(company)
        su = register.match_scaleup(company)
        if p.visa.needs_sponsorship and not (sp or su):
            continue
        signals = [sponsorship_signal(r["description"] or "").label for r in rows]
        if p.visa.needs_sponsorship and signals.count("negative") > len(signals) / 2:
            continue                       # their adverts say they won't sponsor
        skills = Counter()
        for r in rows:
            skills.update(extract_skills(f"{r['title']}\n{r['description'] or ''}"))
        their = [s for s, _ in sorted(skills.items(), key=lambda kv: (-kv[1], kv[0]))[:14]]
        shared = [s for s in their if s in mine]
        if not shared:
            continue
        t = Target(company, (sp or su).name if (sp or su) else "", 0.0, stack=shared, their_stack=their,
                   roles_hiring=list(dict.fromkeys(r["title"] for r in rows))[:5],
                   scaleup=bool(su), new_sponsor=bool(sp and sp.name in new_names), url=rows[0]["url"] or "")
        # how much of your stack they use (absolute), and how much of theirs you cover (relative)
        score = 6 * min(len(shared), 6) + 20 * len(shared) / max(len(their), 1)
        t.reasons.append(f"Uses {', '.join(shared[:6])}, which you have")
        if len(rows) >= 3:
            score += min(10, 2 * len(rows))
            t.reasons.append(f"Hiring actively: {len(rows)} tech roles seen recently, none right for you yet")
        why_not = _why_not_matched(rows)
        if why_not:
            t.reasons.append(why_not)
        if su:
            score += 15
            t.reasons.append("Holds a Scale-up licence: after 6 months you could change employer freely")
        if key in dream:
            score += 20
            t.reasons.append("One of your dream companies")
        if t.new_sponsor:
            score += 10
            t.reasons.append("Newly licensed sponsor: likely planning to hire from abroad")
        if sp and sp.a_rated:
            score += 5
        if sp and TECH_HUBS.search(sp.town or "") and any(
                c.lower().split("(")[0].strip() in (sp.town or "").lower() for c in p.targets.locations):
            score += 5
            t.reasons.append(f"Based in {sp.town.strip()}, one of your target locations")
        if "positive" in signals:
            score += 8
            t.reasons.append("Its adverts say it sponsors visas")
        t.score = round(score, 1)
        out.append(t)
    return sorted(out, key=lambda t: -t.score)[:limit]


def _why_not_matched(rows) -> str:
    reasons = Counter()
    for r in rows:
        b = json.loads(r["score_json"] or "{}")
        for note in b.get("notes", []):
            if note.startswith("Title level"):
                reasons["their open roles are more senior than you're targeting"] += 1
        for bl in b.get("blockers", []):
            if "threshold" in bl:
                reasons["their open roles pay below the visa threshold"] += 1
            elif "clearance" in bl.lower():
                reasons["their open roles need security clearance"] += 1
    if not reasons:
        return ""
    return "No vacancy fits today because " + reasons.most_common(1)[0][0]


# ---------------------------------------------------------------------------- packs
def weekly_room(db: DB, ctx: Context) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    used = db.conn.execute("SELECT COUNT(*) FROM speculative WHERE created_at>=?", (since,)).fetchone()[0]
    return max(0, ctx.settings["speculative"]["max_per_week"] - used)


def template_approach(ctx: Context, t: Target) -> SpeculativeApproach:
    me = ctx.profile.personal
    proof = ctx.cv.experience[0].bullets[0].text if ctx.cv.experience and ctx.cv.experience[0].bullets else ""
    stack = ", ".join(t.stack[:3])
    route = ctx.profile.visa.target_route
    return SpeculativeApproach(
        why_them=t.reasons,
        value_pitch=[f"Hands-on {stack} experience, ready to contribute from the first sprint",
                     "[Add one idea tied to something they shipped recently]"],
        people_to_find=["Engineering Manager", "Senior Software Engineer", "Talent Partner"],
        linkedin_note=f"Hi [First name], I've been following {t.company}'s work with {stack}. I build similar systems "
                      f"({proof[:90].rstrip('. ')}). Could I ask who'd be best to talk to about engineering roles? {me.first_name}"[:280],
        email_subject=f"{stack} engineer interested in {t.company}",
        email_body=f"Hi [First name],\n\n[One sentence on something specific {t.company} has built or said recently.]\n\n"
                   f"I'm a software engineer working with {stack}. Recently: {proof}.\n\nI don't see an open role that fits "
                   f"today, but I'd value a 15-minute chat about where your team is heading, or a pointer to the right "
                   f"person. I would need {route} sponsorship, and I know {t.company} already holds a sponsor licence.\n\n"
                   f"Best,\n{me.full_name}\n{me.linkedin}",
        follow_up=f"Hi [First name], a quick follow-up on my note last week about engineering roles at {t.company}. "
                  f"Happy to send a short summary of my work if useful. Thanks, {me.first_name}",
        tips=["Read their engineering blog or latest release notes and reference one thing.",
              "Connect with an engineer on the team before messaging the manager."],
    )


def build(db: DB, ctx: Context, llm: Optional[LLM], t: Target, say=print) -> Path:
    """Write the approach pack for one target and record it."""
    d = OUTPUT_DIR / "speculative" / f"{date.today():%Y-%m-%d}_{slug(t.company)}"
    d.mkdir(parents=True, exist_ok=True)
    pseudo = Job(source="speculative", source_id=slug(t.company), company=t.company,
                 title=(ctx.profile.targets.roles or ["Software Engineer"])[0], url=t.url,
                 description="Speculative application. Technology this employer uses: " + ", ".join(t.their_stack)
                             + ".\nRoles it advertises: " + "; ".join(t.roles_hiring))
    research_md, sources = "", []
    approach = None
    if llm is not None:
        try:
            research_md, sources = llm.research(
                f"Research the UK employer '{t.company}' (registered as '{t.sponsor_name}') for someone considering a "
                f"speculative job approach. Report, with sources: what it builds and for whom; anything notable in the "
                f"last 12 months (funding, launches, growth, layoffs); its engineering team, tech stack, blog, "
                f"open-source work and talks; and who leads engineering. Be factual and brief; write 'not found' "
                f"rather than guessing.", max_searches=5)
        except LLMError as e:
            say(f"  research skipped: {e}")
        try:
            approach = llm.structured(
                system=system_prompt(ctx.profile, ctx.cv, "a UK tech careers coach who writes outreach people answer"),
                prompt=SPEC_TASK.format(
                    company=t.company, sponsor=t.sponsor_name,
                    scaleup=" (also holds a Scale-up licence)" if t.scaleup else "",
                    stack=", ".join(t.stack) or "unknown", their_stack=", ".join(t.their_stack) or "unknown",
                    roles="; ".join(t.roles_hiring) or "unknown",
                    research=research_md or "No research available.", spelling=ctx.profile.writing.spelling,
                    route=ctx.profile.visa.target_route),
                schema=SpeculativeApproach, effort=ctx.settings["llm"]["tailor_effort"])
        except LLMError as e:
            say(f"  Claude failed ({e}); using the template")
    if approach is None:
        approach = template_approach(ctx, t)

    try:
        cv, _warnings = tailor_cv(llm, ctx, pseudo, t.sponsor_name, None)
    except LLMError:
        cv = keyword_tailor(ctx, pseudo)
    base = slug(ctx.profile.personal.full_name)
    render.cv_docx(cv, ctx.profile.personal, d / f"{base}-cv.docx")
    render.cv_pdf(cv, ctx.profile.personal, d / f"{base}-cv.pdf")

    domain = networking.company_domain(pseudo)
    links = networking.search_links(pseudo, approach.people_to_find[:4])
    contacts = []
    try:
        contacts = networking.hunter_contacts(domain) if domain else []
    except Exception:
        pass
    (d / "approach.md").write_text(
        approach_markdown(t, approach, links, networking.email_patterns(domain), contacts, research_md, sources),
        encoding="utf-8")
    db.conn.execute(
        "INSERT OR REPLACE INTO speculative (company, sponsor_name, score, reasons, created_at, pack_dir, status) "
        "VALUES (?,?,?,?,?,?, 'drafted')",
        (t.company, t.sponsor_name, t.score, json.dumps(t.reasons), now_iso(), str(d)))
    db.commit()
    return d


def approach_markdown(t: Target, a: SpeculativeApproach, links, patterns, contacts, research_md, sources) -> str:
    o = [f"# Speculative approach: {t.company}", "",
         f"Licensed sponsor: {t.sponsor_name}" + (" (also Scale-up)" if t.scaleup else ""), "",
         "## Why this company", ""] + [f"- {x}" for x in dict.fromkeys(a.why_them + t.reasons)]
    o += ["", "## What you could offer them", ""] + [f"- {x}" for x in a.value_pitch]
    o += ["", "## Who to contact", ""] + [f"- {x}" for x in a.people_to_find]
    o += ["", "Search links (open them yourself, logged in to LinkedIn):"] + [f"- [{l}]({u})" for l, u in links]
    if contacts:
        o += ["", "| Name | Role | Email | Confidence |", "|---|---|---|---|"]
        o += [f"| {c.name} | {c.role} | {c.email} | {c.email_confidence} |" for c in contacts]
    if patterns:
        o += ["", "Likely email formats (guesses: verify before sending): " + ", ".join(f"`{x}`" for x in patterns[:3])]
    o += ["", "## LinkedIn connection note", "", a.linkedin_note, "", "## Email", "",
          f"**Subject:** {a.email_subject}", "", a.email_body, "", "## Follow-up (after 7 days)", "", a.follow_up,
          "", "## Before you send", ""] + [f"- {x}" for x in a.tips]
    o += ["", f"When you've sent it, run: `jobstream speculative --sent \"{t.company}\"`"]
    if research_md:
        o += ["", "## Research notes", "", research_md]
    if sources:
        o += ["", "## Sources", ""] + [f"- [{ti}]({u})" for ti, u in sources]
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------------------- tracking
def mark(db: DB, company: str, status: str) -> bool:
    row = db.conn.execute("SELECT company FROM speculative WHERE lower(company)=lower(?) OR lower(company) LIKE ?",
                          (company, f"%{company.lower()}%")).fetchone()
    if not row:
        return False
    if status == "sent":
        db.conn.execute("UPDATE speculative SET status='sent', sent_at=? WHERE company=?", (now_iso(), row[0]))
    else:
        db.conn.execute("UPDATE speculative SET status=? WHERE company=?", (status, row[0]))
    db.commit()
    return True


def due_followups(db: DB) -> list:
    cut = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return db.conn.execute("SELECT * FROM speculative WHERE status='sent' AND sent_at<=?", (cut,)).fetchall()


def unsent(db: DB) -> list:
    return db.conn.execute("SELECT * FROM speculative WHERE status='drafted' ORDER BY created_at DESC").fetchall()


__all__ = ["targets", "build", "mark", "due_followups", "unsent", "weekly_room", "Target"]
