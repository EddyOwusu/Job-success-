"""Prepare (and optionally submit) an application for one job."""
from __future__ import annotations

import json
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


BLOCKED = {
    "login": "the site needs you to sign in or create an account",
    "captcha": "the form has a CAPTCHA",
    "unanswered": "a required question needs your answer",
    "unsure": "an answer needs checking before it's sent",
    "no_form": "couldn't find the application form from the advert link",
    "no_confirmation": "pressed Submit but saw no confirmation: check your email",
    "agency": "agency advert: confirm the employer can sponsor before applying",
    "not_sponsor": "employer not confirmed on the sponsor register",
    "error": "the browser hit an error",
}


def record_attempt(db: DB, uid: str, blocked: str, url: str = "", detail: str = "") -> None:
    """Remember why an automatic application stopped, for the dashboard's "Needs you" list."""
    row = db.get_job(uid)
    if not row:
        return
    extra = json.loads(row["extra"] or "{}")
    if blocked:
        extra["apply_attempt"] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "blocked": blocked,
                                  "why": BLOCKED.get(blocked, blocked), "url": url, "detail": detail[:300]}
    else:
        extra.pop("apply_attempt", None)
    db.conn.execute("UPDATE jobs SET extra=? WHERE uid=?", (json.dumps(extra), row["uid"]))


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
            from ..prompts import ASSESS_RULES
            db.set_assessment(job.uid, assessment.fit_score,
                              json.dumps({**assessment.model_dump(), "rules": ASSESS_RULES}))
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

    plan, net_md = None, ""
    if ctx.settings["apply"].get("networking", "on_demand") == "always":
        try:
            plan = _networking_plan(db, ctx, llm, job, sponsor)
            net_md = networking.plan_markdown(plan)
        except Exception as e:
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
    fresh_extra = json.loads((db.get_job(job.uid) or {"extra": "{}"})["extra"] or "{}")
    db.conn.execute("UPDATE jobs SET extra=? WHERE uid=?", (json.dumps({**fresh_extra, "pack_dir": str(pack.dir)}), job.uid))
    msgs.append(f"Application pack: {pack.dir}")

    submitted = False
    method = "pack"
    if mode in ("auto", "review") and llm is not None and llm.over_budget() and not force:
        msgs.append(f"Today's Claude budget (${llm.budget_usd:.2f}) is used up, so this wasn't sent. The pack is ready; "
                    "apply tomorrow, or raise the budget with `jobstream budget --daily`.")
        mode = "pack"
    if mode == "auto":
        from ..agencies import is_agency
        why = "agency" if is_agency(job.company, job.extra) else "" if sponsor else "not_sponsor"
        if why and not force:
            record_attempt(db, job.uid, why, job.apply_url or job.url)
            msgs.append(f"Not sent automatically: {BLOCKED[why]}. The pack is ready.")
            mode = "pack"
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
            import sys
            # scheduled runs have no console: never pop a browser window up on the screen
            headless = a["headless"] or not (sys.stdin is not None and sys.stdin.isatty())
            res = fill_form(url, ctx, pack, answer_fn, mode=mode, headless=headless, chromium_path=a["chromium_path"])
            submitted = res.submitted
            method = f"browser-{mode}"
            msgs += res.notes
            if res.unanswered_required:
                msgs.append("Unanswered required fields: " + "; ".join(q[:60] for q in res.unanswered_required))
            if mode == "auto":
                detail = "; ".join((res.unanswered_required or res.low_confidence)[:3])
                record_attempt(db, job.uid, "" if submitted else (res.blocked or "no_confirmation"),
                               res.final_url or url, detail)
                if not submitted:
                    msgs.append(f"Not sent: {BLOCKED.get(res.blocked, res.blocked)}. It's on your Needs you list.")
        except Exception as e:
            msgs.append(f"Browser filling failed ({e}). Apply by hand with the pack: {url}")
            if mode == "auto":
                record_attempt(db, job.uid, "error", url, str(e))

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


def _networking_plan(db: DB, ctx: Context, llm, job, sponsor):
    plan = networking.build_plan(llm, ctx, job, sponsor)
    for c in plan.contacts:
        db.add_contact(company=job.company, job_uid=job.uid, name=c.name, role=c.role, email=c.email,
                       email_confidence=c.email_confidence, linkedin=c.linkedin, source=c.source, notes="")
    return plan


def build_networking(db: DB, ctx: Context, llm, uid: str):
    """Networking plan for one job, on request: who to contact and what to say. Saved as networking.md in
    the job's pack (when it has one). Returns (markdown, path or None)."""
    from pathlib import Path
    row = db.get_job(uid)
    if not row:
        raise ValueError(f"No job matching '{uid}'")
    job = db.row_to_job(row)
    plan = _networking_plan(db, ctx, llm, job, row["sponsor_match"])
    md = networking.plan_markdown(plan)
    extra = json.loads(row["extra"] or "{}")
    path = None
    d = extra.get("pack_dir") or next((a["pack_dir"] for a in db.conn.execute(
        "SELECT pack_dir FROM applications WHERE job_uid=? AND pack_dir != '' ORDER BY applied_at DESC", (row["uid"],))), None)
    if d and Path(d).exists():
        path = Path(d) / "networking.md"
        path.write_text(md, encoding="utf-8")
    extra["networking_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.conn.execute("UPDATE jobs SET extra=? WHERE uid=?", (json.dumps(extra), row["uid"]))
    db.commit()
    return md, path


def schedule_followups(db: DB, ctx: Context, uid: str, outreach) -> None:
    now = datetime.now(timezone.utc)
    db.add_followup(uid, now, "networking", "Send the day-0 LinkedIn messages in networking.md" if outreach else
                    "Worth a message to someone at the company? Build a networking plan: jobstream network "
                    + uid.split(":")[-1] + " (or Network on the dashboard)")
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
