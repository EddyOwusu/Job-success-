"""Deep fit assessment of a job with Claude."""
from __future__ import annotations

from .config import Context
from .llm import LLM
from .models import FitAssessment, Job
from .prompts import ASSESS_TASK, job_block, system_prompt


def assess(llm: LLM, ctx: Context, job: Job, sponsor_name: str | None) -> FitAssessment:
    system, prompt = request(ctx, job, sponsor_name)
    return llm.structured(
        system=system, prompt=prompt, schema=FitAssessment,
        effort=ctx.settings["llm"]["assess_effort"],
        model=ctx.settings["llm"].get("assess_model") or None,
    )


def request(ctx: Context, job: Job, sponsor_name: str | None) -> tuple[str, str]:
    """(system, prompt) for one assessment: sent straight away, or as part of a batch."""
    sp = ctx.settings["sponsorship"]
    from .visa import threshold_for, transitional
    floor, why = threshold_for(ctx.profile.visa, ctx.settings)
    note = f"For this candidate the floor is £{floor:,} ({why})."
    if transitional(ctx.profile.visa)["medium_skilled"]:
        note += (" They are already on the Skilled Worker route (first sponsored before 22 July 2025), so they can also be "
                 "sponsored in 'medium skilled' occupations such as IT support, which new applicants cannot.")
    t = ctx.profile.targets
    if ctx.profile.visa.willing_to_relocate and t.anywhere:
        note += (" The candidate will relocate anywhere in the UK, so the job's location and onsite work are not a "
                 "weakness.")
    if not ctx.profile.personal.driving_licence:
        note += (" Whether the candidate holds a driving licence is not stated: if the advert requires one, say so as "
                 "a question to check, not as a gap.")
    from .sponsors import core_name
    here = core_name(job.company)
    def same_employer(cv_company: str) -> bool:      # "Acme Care Services, Riverside House" is Acme
        c = core_name(cv_company.split(",")[0])
        return c == here or c.startswith(here + " ") or here.startswith(c + " ")

    if here and any(same_employer(r.company) for r in ctx.cv.experience if r.end in ("", "present")):
        note += (f" The candidate already works for {job.company} (see the master CV): an internal applicant, which is a "
                 "real advantage. A move into a different occupation still needs a new certificate of sponsorship.")
    task = ASSESS_TASK.format(threshold=sp["general_threshold_gbp"], new_entrant=sp["new_entrant_threshold_gbp"]) + "\n" + note
    return (system_prompt(ctx.profile, ctx.cv, "a blunt, well-informed UK tech recruiter and career coach"),
            job_block(job, sponsor_name) + "\n" + task)
