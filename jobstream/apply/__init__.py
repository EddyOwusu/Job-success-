"""Prepare (and optionally submit) an application for one job."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import ats as ats_mod
from .. import networking
from ..config import OUTPUT_DIR, Context
from ..db import DB
from ..llm import LLM, LLMError
from ..models import FitAssessment, FormAnswers, ScoreBreakdown
from ..tailor import answer_questions, cover_letter, needs_statement, supporting_statement, tailor_cv
from .pack import Pack, write_answers, write_pack


@dataclass
class ApplyOutcome:
    pack: Pack
    submitted: bool
    method: str
    messages: list[str]


def greenhouse_questions(job) -> list[dict]:
    """Form questions from the Greenhouse API, so answers can be prepared before opening a browser."""
    from ..sources import greenhouse

    data = greenhouse.questions(job.ats_token, job.source_id)
    out = []
    for q in data.get("questions", []) + (data.get("location_questions") or []):
        f0 = (q.get("fields") or [{}])[0]
        if f0.get("type") in ("input_file", "input_hidden"):
            continue
        out.append({"label": q.get("label", ""), "required": q.get("required", False), "type": f0.get("type"),
                    "options": [v.get("label") for v in f0.get("values", [])]})
    for section in (data.get("compliance") or []):
        for q in section.get("questions", []):
            f0 = (q.get("fields") or [{}])[0]
            out.append({"label": q.get("label", ""), "required": q.get("required", False), "type": f0.get("type"),
                        "options": [v.get("label") for v in f0.get("values", [])]})
    skip = {"first name", "last name", "email", "phone", "resume/cv", "cover letter"}
    return [q for q in out if q["label"].strip().lower() not in skip]


def check_limits(db: DB, ctx: Context, company: str) -> Optional[str]:
    a = ctx.settings["apply"]
    if db.applications_today() >= a["max_applications_per_day"]:
        return f"Daily limit of {a['max_applications_per_day']} applications reached"
    if db.applications_to_company(company) >= a["max_per_company_per_30_days"]:
        return f"Already applied to {company} {a['max_per_company_per_30_days']}x in 30 days (looks spammy to recruiters)"
    return None


def prepare_and_apply(db: DB, ctx: Context, llm: Optional[LLM], uid: str, mode: Optional[str] = None,
                      force: bool = False) -> ApplyOutcome:
    row = db.get_job(uid)
    if not row:
        raise ValueError(f"No job matching '{uid}'")
    job = db.row_to_job(row)
    mode = mode or ctx.settings["apply"]["mode"]
    msgs: list[str] = []
    if job.source in ("nhs", "jobsacuk") and mode in ("review", "auto", "dry"):
        msgs.append("NHS Jobs and university portals need your own login: the pack is ready to paste in at "
                    + (job.apply_url or job.url))
        mode = "pack"
    if mode != "pack" and not force:
        reason = check_limits(db, ctx, job.company)
        if reason:
            msgs.append(reason + "; building the pack only.")
            mode = "pack"

    sponsor = row["sponsor_match"]
    score = ScoreBreakdown.model_validate_json(row["score_json"]) if row["score_json"] else None
    assessment = FitAssessment.model_validate_json(row["assessment_json"]) if row["assessment_json"] else None
    if llm and not assessment:
        from ..assess import assess
        try:
            assessment = assess(llm, ctx, job, sponsor)
            db.set_assessment(job.uid, assessment.fit_score, assessment.model_dump_json())
            db.commit()
        except LLMError as e:
            msgs.append(f"Assessment skipped: {e}")

    try:
        cv, warnings = tailor_cv(llm, ctx, job, sponsor, assessment)
        letter = cover_letter(llm, ctx, job, sponsor)
    except LLMError as e:
        msgs.append(f"Claude failed ({e}); using keyword tailoring")
        cv, warnings = tailor_cv(None, ctx, job, sponsor, assessment)
        letter = cover_letter(None, ctx, job, sponsor)
    report = ats_mod.check(f"{job.title}\n{job.description}", cv, ctx.profile)
    msgs.append(report.summary())
    msgs += warnings

    answers: Optional[FormAnswers] = None
    if job.ats == "greenhouse" and job.ats_token:
        try:
            qs = greenhouse_questions(job)
            answers = answer_questions(llm, ctx, job, sponsor, qs)
        except Exception as e:
            msgs.append(f"Could not prepare Greenhouse answers: {e}")

    try:
        plan = networking.build_plan(llm, ctx, job, sponsor)
        net_md = networking.plan_markdown(plan)
        for c in plan.contacts:
            db.add_contact(company=job.company, job_uid=job.uid, name=c.name, role=c.role, email=c.email,
                           email_confidence=c.email_confidence, linkedin=c.linkedin, source=c.source, notes="")
    except Exception as e:
        plan, net_md = None, ""
        msgs.append(f"Networking plan failed: {e}")

    statement = None
    if needs_statement(job):
        if llm is None:
            msgs.append("This employer shortlists on a supporting statement: add your Claude key to have it written.")
        else:
            try:
                statement = supporting_statement(llm, ctx, job, sponsor)
                msgs.append("Supporting statement written (supporting-statement.md)")
            except LLMError as e:
                msgs.append(f"Supporting statement failed: {e}")

    pack = write_pack(OUTPUT_DIR, job, ctx.profile.personal, cv, letter, score, assessment, report, warnings,
                      answers, net_md, statement)
    db.set_status(job.uid, "packed")
    msgs.append(f"Application pack: {pack.dir}")

    submitted = False
    method = "pack"
    if mode in ("review", "auto", "dry"):
        from .browser import fill_form

        url = job.apply_url or job.url
        if job.ats == "greenhouse":
            url = f"https://job-boards.greenhouse.io/{job.ats_token}/jobs/{job.source_id}"
        prepared = {a.question: (a.answer, a.confidence if not a.needs_human else "low")
                    for a in (answers.answers if answers else [])}

        def answer_fn(questions: list[dict]) -> dict:
            todo = [q for q in questions if q["label"] not in prepared]
            out = dict(prepared)
            if todo:
                try:
                    fa = answer_questions(llm, ctx, job, sponsor, todo)
                except LLMError as e:
                    from .answers import rule_based_answers
                    msgs.append(f"Claude could not answer form questions ({e})")
                    fa = rule_based_answers(ctx, todo)
                for a in fa.answers:
                    out[a.question] = (a.answer, a.confidence if not a.needs_human else "low")
                write_answers(pack.dir, FormAnswers(answers=(answers.answers if answers else []) + fa.answers))
            return out

        a = ctx.settings["apply"]
        try:
            res = fill_form(url, ctx, pack, answer_fn, mode=mode, headless=a["headless"], chromium_path=a["chromium_path"])
            submitted = res.submitted
            method = f"browser-{mode}"
            msgs += res.notes
            if res.unanswered_required:
                msgs.append("Unanswered required fields: " + "; ".join(q[:60] for q in res.unanswered_required))
        except Exception as e:
            msgs.append(f"Browser filling failed ({e}). Apply by hand with the pack: {url}")

    if submitted:
        from ..learn import snapshot
        fresh = db.get_job(job.uid)
        db.record_application(row, method, str(pack.dir),
                              features=snapshot(fresh, method=method, claude=llm is not None,
                                                statement=statement is not None))
        schedule_followups(db, ctx, job.uid, plan.outreach if plan else None)
        msgs.append("Recorded as applied. Follow-ups scheduled.")
    db.commit()
    return ApplyOutcome(pack, submitted, method, msgs)


def schedule_followups(db: DB, ctx: Context, uid: str, outreach) -> None:
    now = datetime.now(timezone.utc)
    db.add_followup(uid, now, "networking", "Send the day-0 LinkedIn messages in networking.md")
    for d in ctx.settings["followup"]["days"]:
        db.add_followup(uid, now + timedelta(days=d), "follow_up",
                        f"Day {d}: send the follow-up message from networking.md (or check the application portal)")
    db.commit()


def mark_applied(db: DB, ctx: Context, uid: str, notes: str = "") -> None:
    """For applications you sent by hand."""
    row = db.get_job(uid)
    if not row:
        raise ValueError(f"No job matching '{uid}'")
    from ..learn import snapshot
    db.record_application(row, "manual", "", notes, features=snapshot(row, method="manual", claude=False))
    schedule_followups(db, ctx, row["uid"], None)


__all__ = ["prepare_and_apply", "mark_applied", "ApplyOutcome"]
