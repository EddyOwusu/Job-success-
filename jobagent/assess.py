"""Deep fit assessment of a job with Claude."""
from __future__ import annotations

from .config import Context
from .llm import LLM
from .models import FitAssessment, Job
from .prompts import ASSESS_TASK, job_block, system_prompt


def assess(llm: LLM, ctx: Context, job: Job, sponsor_name: str | None) -> FitAssessment:
    sp = ctx.settings["sponsorship"]
    task = ASSESS_TASK.format(threshold=sp["general_threshold_gbp"], new_entrant=sp["new_entrant_threshold_gbp"])
    return llm.structured(
        system=system_prompt(ctx.profile, ctx.cv, "a blunt, well-informed UK tech recruiter and career coach"),
        prompt=job_block(job, sponsor_name) + "\n" + task,
        schema=FitAssessment,
        effort=ctx.settings["llm"]["assess_effort"],
    )
