"""Interview preparation pack, built the moment an application turns into an interview.

Two steps:
 1. Research (Claude with web search): the organisation, recent news, tech stack,
    how it interviews, and current visa facts from gov.uk. Only the company, role
    and advert are sent for this step, never your personal details.
 2. Prep (Claude with your dossier): likely questions with answer outlines built from
    your real stories, technical topics to revise, how to talk about sponsorship,
    salary, questions to ask, and a checklist.
Without Claude it still writes a useful template from your master CV and the advert.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .config import OUTPUT_DIR, Context
from .db import DB
from .llm import LLM, LLMError
from .models import Job
from .prompts import job_block, system_prompt
from .skills import extract_weighted
from .text import slug


# ---------------------------------------------------------------------------- models
class PrepQuestion(BaseModel):
    category: str = Field(description="behavioural | technical | role | values | motivation | visa")
    question: str
    why_they_ask: str
    answer_outline: list[str] = Field(description="3-5 bullet points using only the candidate's real experience")


class TopicPlan(BaseModel):
    topic: str
    why_it_matters_here: str
    what_to_revise: list[str]
    practice: str = Field(description="One concrete exercise, e.g. 'design a rate limiter on paper in 30 minutes'")


class StarStory(BaseModel):
    title: str
    situation: str
    task: str
    action: str
    result: str
    use_for: list[str] = Field(description="Competencies or questions this story answers")


class Concern(BaseModel):
    concern: str
    answer: str


class SponsorshipTalk(BaseModel):
    when_to_raise: str
    script: str = Field(description="What the candidate says, in their voice, 60-120 words, confident and factual")
    likely_concerns: list[Concern]
    facts_to_have_ready: list[str]


class InterviewPrep(BaseModel):
    process_overview: str = Field(description="Likely stages and format for this employer and role")
    company_brief: list[str] = Field(description="Key facts worth knowing, each one specific")
    tell_me_about_yourself: str = Field(description="A 60-90 second answer in the candidate's voice")
    why_this_role: str = Field(description="A specific answer to 'Why us / why this role?' in the candidate's voice")
    questions: list[PrepQuestion]
    technical_topics: list[TopicPlan]
    stories: list[StarStory]
    sponsorship: SponsorshipTalk
    salary_script: str
    gaps_to_prepare_for: list[Concern]
    questions_to_ask: list[str]
    checklist: list[str]


# ---------------------------------------------------------------------------- prompts
RESEARCH_PROMPT = """Research this employer for someone preparing for an interview in the UK.

Employer: {company}
Role: {title}
Location: {location}
Sector: {sector}

Find and report, citing sources:
1. What the organisation does, its size, and anything notable from the last 12 months
   (funding, results, launches, restructures, layoffs, inspections or ratings for NHS bodies).
2. The team or department behind this role and its technology (engineering blog, GitHub,
   conference talks, tech stack mentions, digital strategy for NHS trusts / universities).
3. How it interviews for similar roles (stages, take-home tests, values-based questions).
   Glassdoor, blogs and the organisation's own careers pages are fine.
4. Its values, mission statements or frameworks it expects candidates to know (for NHS
   trusts: the NHS values and the trust's own values).
5. From gov.uk: what a UK employer must do and pay to sponsor a Skilled Worker (certificate
   of sponsorship fee, Immigration Skills Charge) as of today, with the figures.

Be factual and concise. Write "not found" rather than guessing. Use British English.

Advert summary:
{advert}
"""

PREP_TASK = """The candidate has an interview for this job. Prepare them.

Stage: {stage}
Interviewers (if known): {interviewers}
Candidate's notes: {notes}

Research notes about the employer (from web search; trust them over your own memory):
<research>
{research}
</research>

Write the prep:
- process_overview: what to expect at this stage and after it, for this kind of employer
  (NHS: values-based panel, often a short presentation; universities: panel, sometimes a task;
  tech companies: screen, technical, system design, behavioural).
- questions: 12-18 likely questions across behavioural, technical, role, values and motivation,
  plus 1-2 on visa or right to work. Answer outlines must use only the candidate's real
  experience from the dossier; where they have no direct example, say how to bridge honestly.
- technical_topics: 4-8 topics from the advert and the research, with what to revise and one
  practice exercise each.
- stories: 5-7 STAR stories built only from the dossier, each mapped to competencies.
- sponsorship: when to raise it (usually: confirm early with the recruiter, not in a technical
  round), a short confident script, likely employer concerns (cost, timing, process, the
  candidate leaving) with factual answers, and the facts to have ready (salary threshold
  £{threshold:,}, start date, current visa status: {visa_status}). Use the research for the
  current fees and charges, and say if they weren't found.
- salary_script: how to answer the salary question, keeping the offer at or above
  £{threshold:,} for the visa, and the candidate's own expectations: {expectation}.
- gaps_to_prepare_for: the weaknesses an interviewer will probe, with an honest answer for each.
- questions_to_ask: 6-8 sharp questions that show research (cite something specific).
- checklist: the day-before and on-the-day list.
"""


# ---------------------------------------------------------------------------- build
def prep_dir(db: DB, job: Job) -> Path:
    row = db.conn.execute("SELECT pack_dir FROM applications WHERE job_uid=? AND pack_dir!='' "
                          "ORDER BY applied_at DESC LIMIT 1", (job.uid,)).fetchone()
    if row and row[0] and Path(row[0]).exists():
        return Path(row[0])
    d = OUTPUT_DIR / "interviews" / f"{date.today():%Y-%m-%d}_{slug(job.company)}_{slug(job.title)[:40]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def research(llm: LLM, job: Job) -> tuple[str, list[tuple[str, str]]]:
    return llm.research(RESEARCH_PROMPT.format(
        company=job.company, title=job.title, location=job.location,
        sector=job.extra.get("sector") or "technology company", advert=(job.description or "")[:6000]))


def build_prep(llm: Optional[LLM], ctx: Context, db: DB, job: Job, sponsor: Optional[str], *,
               stage: str = "first interview", interviewers: str = "", notes: str = "") -> tuple[Path, list[str]]:
    """Write interview-prep.md for a job. Returns (path, messages)."""
    msgs: list[str] = []
    out = prep_dir(db, job) / "interview-prep.md"
    if llm is None:
        out.write_text(template_prep(ctx, job, stage), encoding="utf-8")
        msgs.append("Claude not configured: wrote a template prep pack from your master CV.")
        return out, msgs

    notes_md, sources = "", []
    try:
        notes_md, sources = research(llm, job)
    except LLMError as e:
        msgs.append(f"Web research skipped: {e}")
    sp = ctx.settings["sponsorship"]
    from .visa import threshold_for
    threshold, _ = threshold_for(ctx.profile.visa, ctx.settings)
    task = PREP_TASK.format(
        stage=stage, interviewers=interviewers or "not known", notes=notes or "none",
        research=notes_md or "No research available: rely on the advert and say what to look up.",
        threshold=threshold, visa_status=ctx.profile.visa.current_status or "not stated",
        expectation=ctx.profile.standard_answers.get("salary_expectation", "not stated"),
    )
    try:
        prep = llm.structured(
            system=system_prompt(ctx.profile, ctx.cv, "an experienced UK interview coach and former hiring manager"),
            prompt=job_block(job, sponsor) + "\n" + task, schema=InterviewPrep,
            effort=ctx.settings["llm"]["tailor_effort"], max_tokens=20000,
        )
    except LLMError as e:
        msgs.append(f"Claude prep failed ({e}); wrote the template instead.")
        out.write_text(template_prep(ctx, job, stage), encoding="utf-8")
        return out, msgs
    out.write_text(prep_markdown(job, prep, stage, notes_md, sources), encoding="utf-8")
    (out.parent / "interview-prep.json").write_text(prep.model_dump_json(indent=2), encoding="utf-8")
    msgs.append(f"Interview prep written: {out}")
    return out, msgs


# ---------------------------------------------------------------------------- output
def prep_markdown(job: Job, p: InterviewPrep, stage: str, research_md: str, sources: list[tuple[str, str]]) -> str:
    o = [f"# Interview prep: {job.title} at {job.company}", "", f"Stage: {stage}. Link: {job.url}", "",
         "## What to expect", "", p.process_overview, "", "## The organisation in brief", ""]
    o += [f"- {x}" for x in p.company_brief]
    o += ["", "## Tell me about yourself", "", p.tell_me_about_yourself, "",
          "## Why this role, why us", "", p.why_this_role, "", "## Likely questions", ""]
    for cat in ("motivation", "role", "behavioural", "values", "technical", "visa"):
        qs = [q for q in p.questions if q.category == cat]
        if not qs:
            continue
        o += [f"### {cat.title()}", ""]
        for q in qs:
            o += [f"**{q.question}**", f"_Why they ask: {q.why_they_ask}_", ""] + [f"- {b}" for b in q.answer_outline] + [""]
    o += ["## Your stories (STAR)", ""]
    for s in p.stories:
        o += [f"### {s.title}", f"Use for: {', '.join(s.use_for)}", "",
              f"- **Situation:** {s.situation}", f"- **Task:** {s.task}", f"- **Action:** {s.action}",
              f"- **Result:** {s.result}", ""]
    o += ["## Technical topics to revise", ""]
    for t in p.technical_topics:
        o += [f"### {t.topic}", t.why_it_matters_here, ""] + [f"- {x}" for x in t.what_to_revise] + [f"- Practice: {t.practice}", ""]
    s = p.sponsorship
    o += ["## Talking about sponsorship", "", f"**When:** {s.when_to_raise}", "", f"**What to say:** {s.script}", "",
          "**If they're worried about...**", ""] + [f"- *{c.concern}*: {c.answer}" for c in s.likely_concerns]
    o += ["", "**Facts to have ready**", ""] + [f"- {f}" for f in s.facts_to_have_ready]
    o += ["", "## Salary", "", p.salary_script, "", "## Gaps they may probe", ""]
    o += [f"- *{g.concern}*: {g.answer}" for g in p.gaps_to_prepare_for]
    o += ["", "## Questions to ask them", ""] + [f"- {q}" for q in p.questions_to_ask]
    o += ["", "## Checklist", ""] + [f"- [ ] {c}" for c in p.checklist]
    if research_md:
        o += ["", "## Research notes", "", research_md]
    if sources:
        o += ["", "## Sources", ""] + [f"- [{t}]({u})" for t, u in sources]
    return "\n".join(o) + "\n"


def template_prep(ctx: Context, job: Job, stage: str) -> str:
    """No-Claude version: the advert's skills plus your own stories, laid out to fill in."""
    skills = sorted(extract_weighted(job.description).items(), key=lambda kv: -kv[1])
    have = {s.name.lower() for s in ctx.profile.skills}
    sp = ctx.settings["sponsorship"]
    from .visa import threshold_for
    threshold, _ = threshold_for(ctx.profile.visa, ctx.settings)
    o = [f"# Interview prep: {job.title} at {job.company}", "", f"Stage: {stage}. Link: {job.url}", "",
         "Template (add your Claude API key for researched, tailored prep).", "",
         "## Research before the interview", "",
         f"- [ ] What {job.company} does, and its news from the last 12 months",
         "- [ ] The team's tech: engineering blog, GitHub, talks",
         "- [ ] Interview reports for this role (Glassdoor)",
         "- [ ] Their values or mission statement (NHS: the NHS values and the trust's own)", "",
         "## Skills the advert stresses", ""]
    o += [f"- {k} ({'required' if w >= 1 else 'nice to have'}): " + ("prepare an example" if k.lower() in have else "a gap: say how you'd learn it")
          for k, w in skills[:12]]
    o += ["", "## Your stories (fill in Situation / Task / Action / Result)", ""]
    for st in ctx.cv.stories:
        o += [f"### {st.title}", st.text.strip(), ""]
    for role in ctx.cv.experience[:2]:
        for b in role.bullets[:3]:
            o += [f"- From {role.company}: {b.text}"]
    o += ["", "## Talking about sponsorship", "",
          "- Raise it with the recruiter early, not in a technical round.",
          f"- Say: \"I'll need {ctx.profile.visa.target_route} sponsorship. It's straightforward: the role is at the right "
          f"skill level and the salary meets the £{threshold:,} threshold. I can start {ctx.profile.visa.earliest_start or 'soon'}.\"",
          "- Have ready: your current visa status, earliest start date, and the salary floor.", "",
          "## Questions to ask", "", "- What does success look like in the first 6 months?",
          "- What's the biggest technical challenge the team faces this year?",
          "- How do you support people new to the UK or to the organisation?", "",
          "## Checklist", "", "- [ ] Re-read the advert and your application", "- [ ] Test camera, mic and link",
          "- [ ] Two questions ready that show you researched them"]
    return "\n".join(o) + "\n"


def summary_line(path: Path) -> str:
    try:
        data = json.loads((path.parent / "interview-prep.json").read_text(encoding="utf-8"))
        return f"{len(data['questions'])} questions, {len(data['stories'])} stories, {len(data['technical_topics'])} topics"
    except Exception:
        return "template"
