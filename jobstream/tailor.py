"""Tailored CV, cover letter and form answers, with a guard against invented facts."""
from __future__ import annotations

import json
import re
from typing import Optional

from .config import Context
from .llm import LLM
from .models import (CoverLetter, FitAssessment, FormAnswers, Job, MasterCV, Profile, SupportingStatement,
                     TailoredCV, TailoredRole)
from .prompts import ANSWERS_TASK, COVER_TASK, STATEMENT_TASK, TAILOR_TASK, job_block, system_prompt
from .skills import canonical, extract_skills, extract_weighted

WRITER = "an expert UK tech CV writer who knows how applicant tracking systems parse CVs"


# ---------------------------------------------------------------------------- truth guard
def _source_text(profile: Profile, cv: MasterCV) -> str:
    """Only career facts (not settings like word limits or salary wishes, whose numbers would leak in)."""
    facts = profile.model_dump(include={"skills", "education", "certifications", "languages"})
    facts["years_experience"] = profile.targets.years_experience
    return json.dumps(facts) + json.dumps(cv.model_dump())


def _numbers(text: str) -> set[str]:
    # "2026." at the end of a sentence is 2026
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", text or "") if any(c.isdigit() for c in n)}


def guard(tailored: TailoredCV, profile: Profile, cv: MasterCV) -> tuple[TailoredCV, list[str]]:
    """Remove anything the dossier does not support. Returns the cleaned CV and warnings."""
    warnings: list[str] = []
    source = _source_text(profile, cv).lower()
    source_numbers = _numbers(source)
    known_skills = {canonical(s.name).lower() for s in profile.skills} | {
        s.lower() for s in extract_skills(source)
    }

    def skill_ok(s: str) -> bool:
        if canonical(s).lower() in known_skills or s.lower() in source:
            return True
        # "Microsoft 365 (Office 365)", "Networking (DNS, routers)": every skill named is one you have
        named = {x.lower() for x in extract_skills(s)}
        if named and named <= known_skills and canonical(s.split("(")[0].strip()).lower() in known_skills | named:
            return True
        # "Hardware and device setup": every word is in your CV
        words = [w for w in re.findall(r"[a-z0-9]{3,}", s.lower()) if w not in ("and", "the", "for", "with")]
        return bool(words) and all(w in source for w in words)

    skills = []
    for s in tailored.skills:
        if skill_ok(s):
            skills.append(s)
        else:
            warnings.append(f"Removed skill not in your profile: {s}")
    tailored.skills = list(dict.fromkeys(skills))

    # A company can appear twice (e.g. promoted: "Support Worker" then "IT Consultant"), so roles are matched
    # on company and start date, then company and title, then the first unused role at that company.
    used: set[int] = set()

    def source_role(r: TailoredRole) -> int | None:
        same = [i for i, x in enumerate(cv.experience) if x.company.lower() == r.company.lower() and i not in used]
        for test in (lambda x: x.start == r.start, lambda x: x.title.lower() == r.title.lower(), lambda x: True):
            hit = next((i for i in same if test(cv.experience[i])), None)
            if hit is not None:
                return hit
        return None

    roles: list[tuple[int, TailoredRole]] = []
    for r in tailored.experience:
        i = source_role(r)
        if i is None:
            warnings.append(f"Removed role not in your master CV: {r.title} at {r.company}")
            continue
        used.add(i)
        src = cv.experience[i]
        r.title, r.start, r.end, r.location = src.title, src.start, src.end, src.location or r.location
        r.company, r.kind = src.company, src.kind
        bullets = []
        for b in r.bullets:
            invented = _numbers(b) - source_numbers
            if invented:
                warnings.append(f"Dropped a bullet with numbers not in your CV ({', '.join(sorted(invented))}): {b[:80]}")
            else:
                bullets.append(b)
        r.bullets = bullets or ([] if src.kind == "other" else [x.text for x in src.bullets[:3]])
        roles.append((i, r))
    # never silently lose a job from the history (gaps raise questions)
    for i, src in enumerate(cv.experience):
        if i not in used:
            roles.append((i, TailoredRole(company=src.company, title=src.title, location=src.location, kind=src.kind,
                                          start=src.start, end=src.end,
                                          bullets=[] if src.kind == "other" else [b.text for b in src.bullets[:2]])))
    tailored.experience = [r for _, r in sorted(roles, key=lambda x: x[0])]

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
        keep = 0 if r.kind == "other" else (6 if i < 2 else 3)
        roles.append(TailoredRole(company=r.company, title=r.title, location=r.location, start=r.start, kind=r.kind,
                                  end=r.end, bullets=[b.text for b in ranked[:keep]]))
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


def needs_statement(job: Job) -> bool:
    """NHS, universities and most public bodies shortlist on a supporting statement."""
    return job.extra.get("sector") in ("nhs", "university") or bool(
        re.search(r"person specification|supporting statement|essential criteria", job.description or "", re.I))


def supporting_statement(llm: Optional[LLM], ctx: Context, job: Job, sponsor: str | None) -> Optional[SupportingStatement]:
    if llm is None:
        return None
    return llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, WRITER),
        prompt=job_block(job, sponsor) + "\n" + STATEMENT_TASK,
        schema=SupportingStatement, effort=ctx.settings["llm"]["tailor_effort"],
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
