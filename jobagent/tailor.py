"""Tailored CV, cover letter and form answers, with a guard against invented facts."""
from __future__ import annotations

import json
import re
from typing import Optional

from .config import Context
from .llm import LLM
from .models import (CoverLetter, FitAssessment, FormAnswers, Job, MasterCV, Profile, TailoredCV,
                     TailoredRole)
from .prompts import ANSWERS_TASK, COVER_TASK, TAILOR_TASK, job_block, system_prompt
from .skills import canonical, extract_skills, extract_weighted

WRITER = "an expert UK tech CV writer who knows how applicant tracking systems parse CVs"


# ---------------------------------------------------------------------------- truth guard
def _source_text(profile: Profile, cv: MasterCV) -> str:
    """Only career facts (not settings like word limits or salary wishes, whose numbers would leak in)."""
    facts = profile.model_dump(include={"skills", "education", "certifications", "languages"})
    facts["years_experience"] = profile.targets.years_experience
    return json.dumps(facts) + json.dumps(cv.model_dump())


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,.]*", text or "") if any(c.isdigit() for c in n)}


def guard(tailored: TailoredCV, profile: Profile, cv: MasterCV) -> tuple[TailoredCV, list[str]]:
    """Remove anything the dossier does not support. Returns the cleaned CV and warnings."""
    warnings: list[str] = []
    source = _source_text(profile, cv).lower()
    source_numbers = _numbers(source)
    known_skills = {canonical(s.name).lower() for s in profile.skills} | {
        s.lower() for s in extract_skills(source)
    }

    skills = []
    for s in tailored.skills:
        if canonical(s).lower() in known_skills or s.lower() in source:
            skills.append(s)
        else:
            warnings.append(f"Removed skill not in your profile: {s}")
    tailored.skills = list(dict.fromkeys(skills))

    by_company = {r.company.lower(): r for r in cv.experience}
    roles = []
    for r in tailored.experience:
        src = by_company.get(r.company.lower())
        if not src:
            warnings.append(f"Removed role not in your master CV: {r.title} at {r.company}")
            continue
        r.title, r.start, r.end, r.location = src.title, src.start, src.end, src.location or r.location
        bullets = []
        for b in r.bullets:
            invented = _numbers(b) - source_numbers
            if invented:
                warnings.append(f"Dropped a bullet with numbers not in your CV ({', '.join(sorted(invented))}): {b[:80]}")
            else:
                bullets.append(b)
        r.bullets = bullets or [x.text for x in src.bullets[:3]]
        roles.append(r)
    # never silently lose a job from the history (gaps raise questions)
    present = {r.company.lower() for r in roles}
    for src in cv.experience:
        if src.company.lower() not in present:
            roles.append(TailoredRole(company=src.company, title=src.title, location=src.location,
                                      start=src.start, end=src.end, bullets=[b.text for b in src.bullets[:2]]))
    order = {r.company.lower(): i for i, r in enumerate(cv.experience)}
    tailored.experience = sorted(roles, key=lambda r: order.get(r.company.lower(), 99))

    def _supported(line: str) -> bool:
        words = [w for w in re.findall(r"[a-z]{4,}", line.lower())]
        return not words or sum(w in source for w in words) / len(words) >= 0.6

    for field in ("certifications", "education"):
        kept = []
        for line in getattr(tailored, field):
            if _supported(line):
                kept.append(line)
            else:
                warnings.append(f"Removed {field[:-1]} not in your CV: {line}")
        setattr(tailored, field, kept)
    for text_field in ("summary", "headline"):
        invented = _numbers(getattr(tailored, text_field)) - source_numbers
        if invented:
            warnings.append(f"{text_field.title()} had numbers not in your CV ({', '.join(invented)}); using your master {text_field}")
            setattr(tailored, text_field, getattr(cv, text_field) or getattr(tailored, text_field))
    return tailored, warnings


# ---------------------------------------------------------------------------- offline version
def keyword_tailor(ctx: Context, job: Job) -> TailoredCV:
    """No-LLM tailoring: reorder skills and bullets by relevance to the advert."""
    weights = extract_weighted(f"{job.title}\n{job.description}")
    wl = {k.lower(): v for k, v in weights.items()}

    def rel(tags: list[str], text: str) -> float:
        found = {canonical(t).lower() for t in tags} | {s.lower() for s in extract_skills(text)}
        return sum(wl.get(f, 0) for f in found)

    skills = sorted(ctx.profile.skills, key=lambda s: (-wl.get(canonical(s.name).lower(), 0), -s.level))
    roles = []
    for i, r in enumerate(ctx.cv.experience):
        ranked = sorted(r.bullets, key=lambda b: -rel(b.tags, b.text))
        roles.append(TailoredRole(company=r.company, title=r.title, location=r.location, start=r.start,
                                  end=r.end, bullets=[b.text for b in ranked[: 6 if i < 2 else 3]]))
    projects = sorted(ctx.cv.projects, key=lambda p: -rel(p.tags, p.description))
    return TailoredCV(
        headline=ctx.cv.headline or job.title,
        summary=ctx.cv.summary.strip(),
        skills=[s.name for s in skills][:18],
        experience=roles,
        projects=[f"{p.name}: {p.description}" + (f" ({p.link})" if p.link else "") for p in projects[:3]
                  if rel(p.tags, p.description) > 0],
        education=[f"{e.degree}, {e.institution}" + (f" ({e.year})" if e.year else "") for e in ctx.cv.education],
        certifications=list(ctx.cv.certifications or ctx.profile.certifications),
    )


def template_cover_letter(ctx: Context, job: Job) -> CoverLetter:
    p = ctx.profile
    top = [b.text for r in ctx.cv.experience[:1] for b in r.bullets[:2]]
    paras = [
        f"I am applying for the {job.title} role at {job.company}. {ctx.cv.summary.strip()}",
        "Some recent work that matches what you are looking for: " + "; ".join(top) + ".",
        f"I would welcome the chance to talk about how I can help {job.company}.",
    ]
    if p.visa.needs_sponsorship:
        paras.insert(2, f"I would need {p.visa.target_route} visa sponsorship. {p.visa.current_status}.".strip())
    return CoverLetter(greeting="Dear Hiring Team,", paragraphs=paras, sign_off=f"Kind regards,\n{p.personal.full_name}")


# ---------------------------------------------------------------------------- with Claude
def tailor_cv(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None,
              assessment: Optional[FitAssessment]) -> tuple[TailoredCV, list[str]]:
    if llm is None:
        return keyword_tailor(ctx, job), ["Claude not configured: used keyword tailoring only"]
    task = TAILOR_TASK.format(
        talking_points="\n".join(f"- {t}" for t in (assessment.talking_points if assessment else [])) or "- (none)",
        keywords=", ".join(assessment.keywords_to_mirror if assessment else []) or "(none)",
    )
    out = llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, WRITER),
        prompt=job_block(job, sponsor) + "\n" + task,
        schema=TailoredCV, effort=ctx.settings["llm"]["tailor_effort"],
    )
    return guard(out, ctx.profile, ctx.cv)


def cover_letter(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None) -> CoverLetter:
    if llm is None:
        return template_cover_letter(ctx, job)
    task = COVER_TASK.format(max_words=ctx.profile.writing.cover_letter_max_words,
                             name=ctx.profile.personal.full_name, tone=ctx.profile.writing.tone)
    return llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, WRITER),
        prompt=job_block(job, sponsor) + "\n" + task,
        schema=CoverLetter, effort=ctx.settings["llm"]["tailor_effort"],
    )


def answer_questions(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None,
                     questions: list[dict]) -> FormAnswers:
    """questions: [{"label": str, "required": bool, "type": str, "options": [str]}]"""
    if not questions:
        return FormAnswers(answers=[])
    if llm is None:
        from .apply.answers import rule_based_answers
        return rule_based_answers(ctx, questions)
    q_text = "\n".join(
        f"{i + 1}. {q['label']}" + (" (required)" if q.get("required") else "")
        + (f" [type: {q.get('type')}]" if q.get("type") else "")
        + (f" options: {q['options']}" if q.get("options") else "")
        for i, q in enumerate(questions)
    )
    std = "\n".join(f"  - {k}: {v}" for k, v in ctx.profile.standard_answers.items())
    task = ANSWERS_TASK.format(standard_answers=std or "  (none)", questions=q_text,
                               needs_sponsorship="Yes" if ctx.profile.visa.needs_sponsorship else "No")
    return llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, "a careful job-application assistant"),
        prompt=job_block(job, sponsor) + "\n" + task,
        schema=FormAnswers, effort="medium",
    )
