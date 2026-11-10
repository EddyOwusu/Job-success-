"""The application pack: everything needed to apply for one job, in one folder."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .. import render
from ..ats import ATSReport
from ..models import CoverLetter, FitAssessment, FormAnswers, Job, Personal, ScoreBreakdown, TailoredCV
from ..text import slug


@dataclass
class Pack:
    dir: Path
    cv_docx: Path
    cv_pdf: Path
    letter_docx: Path
    letter_pdf: Path
    cover_letter_text: str
    answers: FormAnswers = field(default_factory=lambda: FormAnswers(answers=[]))


def pack_dir(root: Path, job: Job) -> Path:
    return root / "applications" / f"{date.today():%Y-%m-%d}_{slug(job.company)}_{slug(job.title)[:40]}"


def write_pack(root: Path, job: Job, person: Personal, cv: TailoredCV, letter: CoverLetter,
               score: Optional[ScoreBreakdown], assessment: Optional[FitAssessment], ats: ATSReport,
               warnings: list[str], answers: Optional[FormAnswers] = None,
               networking_md: str = "") -> Pack:
    d = pack_dir(root, job)
    d.mkdir(parents=True, exist_ok=True)
    base = f"{slug(person.full_name)}"
    cv_docx = render.cv_docx(cv, person, d / f"{base}-cv.docx")
    cv_pdf = render.cv_pdf(cv, person, d / f"{base}-cv.pdf")
    letter_docx = render.letter_docx(letter, person, job.company, d / f"{base}-cover-letter.docx")
    letter_pdf = render.letter_pdf(letter, person, job.company, d / f"{base}-cover-letter.pdf")
    (d / "cv.md").write_text(render.cv_markdown(cv, person), encoding="utf-8")
    letter_text = render.letter_markdown(letter, person, job.company)
    (d / "cover-letter.md").write_text(letter_text, encoding="utf-8")

    lines = [f"# {job.title} at {job.company}", "", f"- Location: {job.location}", f"- Link: {job.url}",
             f"- Apply: {job.apply_url or job.url}"]
    if job.salary_min or job.salary_max:
        lines.append(f"- Salary: £{job.salary_min or '?'} - £{job.salary_max or '?'}")
    if score:
        lines += ["", f"## Keyword score: {score.total}/100",
                  f"- Matched skills: {', '.join(score.matched_skills) or '-'}",
                  f"- Missing skills: {', '.join(score.missing_skills) or '-'}"]
        lines += [f"- Note: {n}" for n in score.notes]
    if assessment:
        a = assessment
        lines += ["", f"## Claude's assessment: {a.fit_score}/100, {a.verdict}",
                  f"- Sponsorship likelihood: {a.sponsorship_likelihood} ({a.sponsorship_evidence})",
                  f"- Salary meets visa threshold: {a.salary_meets_visa_threshold}",
                  f"- Seniority: {a.seniority_match}", "", "**Strengths**"] + [f"- {x}" for x in a.strengths]
        lines += ["", "**Gaps**"] + [f"- {x}" for x in a.gaps]
        lines += ["", "**Red flags**"] + [f"- {x}" for x in a.red_flags or ["none"]]
        lines += ["", "**Talking points for interviews and messages**"] + [f"- {x}" for x in a.talking_points]
    lines += ["", "## ATS check", ats.summary()]
    if warnings:
        lines += ["", "## Things the fact-checker removed or changed"] + [f"- {w}" for w in warnings]
    lines += ["", "## The advert", "", job.description]
    (d / "job.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if answers and answers.answers:
        write_answers(d, answers)
    if networking_md:
        (d / "networking.md").write_text(networking_md, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"uid": job.uid, "company": job.company, "title": job.title,
                                             "url": job.url, "apply_url": job.apply_url}, indent=2))
    return Pack(d, cv_docx, cv_pdf, letter_docx, letter_pdf, "\n\n".join(letter.paragraphs), answers or FormAnswers(answers=[]))


def write_answers(d: Path, answers: FormAnswers) -> None:
    out = ["# Application form answers", "", "Check every answer marked CHECK before submitting.", ""]
    for a in answers.answers:
        flag = " **CHECK**" if a.needs_human or a.confidence == "low" else ""
        out += [f"### {a.question}{flag}", "", a.answer or "_(no answer)_", ""]
    (d / "answers.md").write_text("\n".join(out), encoding="utf-8")
