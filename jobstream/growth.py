"""Turn skill gaps into portfolio projects.

The agent sees every advert you nearly match. When the same missing skill keeps
appearing, the fastest fix is a small, public project that proves you can use it.
This module measures the gaps, plans a two-week project for the most valuable one,
tracks it, and tells you exactly what to add to your profile and master CV when
it's done. It never adds a skill for you: you add it once you have really built it.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .config import OUTPUT_DIR, Context
from .db import DB, now_iso
from .llm import LLM, LLMError
from .prompts import system_prompt
from .skills import canonical
from .text import slug

MIN_JOBS = 8


@dataclass
class Gap:
    skill: str
    share: float                    # of your good-fit jobs that ask for it
    jobs: int
    required_share: float           # of those, how often it's a requirement rather than a nice-to-have
    employers: list[str] = field(default_factory=list)
    unlocks: int = 0                # near-miss jobs that would reach your shortlist with this skill
    status: str = ""                # planned | in_progress | done | ""


class Milestone(BaseModel):
    days: str = Field(description="e.g. 'Days 1-2'")
    goal: str
    tasks: list[str]


class ProjectPlan(BaseModel):
    title: str
    one_line: str = Field(description="What it is, in one sentence a recruiter would understand")
    why_this_project: str = Field(description="Why this project, for this candidate and these employers")
    builds_on: list[str] = Field(description="Skills the candidate already has that the project uses")
    milestones: list[Milestone] = Field(description="A two-week plan, part-time, in 4-6 steps")
    definition_of_done: list[str]
    what_to_publish: list[str] = Field(description="Repo contents, README sections, demo, short write-up")
    cv_bullets_when_done: list[str] = Field(description="Bullet templates with [placeholders] for results the candidate must measure")
    interview_talking_points: list[str]
    stretch_goals: list[str]
    what_to_study_first: list[str] = Field(description="Topics and official documentation to read, by name. No URLs.")


PLAN_TASK = """Plan a small portfolio project so the candidate can honestly add **{skill}** to their CV.

Why it matters: {skill} is asked for in {share:.0%} of the jobs the candidate nearly matches
({jobs} adverts; a hard requirement in {required:.0%} of them). Employers asking for it include:
{employers}.
What those adverts say about it:
{snippets}

The project must:
- be finishable in two weeks of evenings (about 20-25 hours) by this candidate
- use {skill} for real, in the way those adverts describe, not as a toy add-on
- build on what the candidate already knows (see the dossier) so most of the effort goes into
  the new skill
- relate to the sectors hiring them (the employers above) where that's natural
- end in something public and checkable: a repository with a clear README, and ideally a
  running demo or a short write-up of what was measured
- be specific. "Deploy an app to Kubernetes" is too vague; say which app, which features of
  the tool, and what gets measured.

cv_bullets_when_done are templates: use [placeholders] for any result the candidate has to
measure. Never write a number they haven't produced yet.
what_to_study_first: name topics and official documentation only. Do not write URLs.
"""

# Fallback ideas when Claude isn't configured: (project, what to do, what to measure)
IDEAS: dict[str, tuple[str, list[str], str]] = {
    "Kubernetes": ("Deploy one of your existing APIs to a local Kubernetes cluster",
                   ["Containerise the API and run it on kind or minikube", "Write Deployment, Service and Ingress manifests",
                    "Add health probes, resource limits and a HorizontalPodAutoscaler", "Do a zero-downtime rolling update"],
                   "requests served during a rolling update, and pod scaling under load"),
    "Terraform": ("Provision the infrastructure for one of your projects as code",
                  ["Write Terraform for a network, a database and a compute service", "Use remote state and variables per environment",
                   "Add a plan-on-pull-request, apply-on-merge pipeline", "Destroy and recreate it from scratch"],
                  "time to recreate the whole environment from nothing"),
    "TypeScript": ("Rebuild a small front end or API client of yours in strict TypeScript",
                   ["Turn on strict mode", "Type the API responses end to end", "Add unit tests", "Publish it with a typed README example"],
                   "bugs caught by the compiler that the JavaScript version had"),
    "Testing": ("Add a real test suite and CI gate to an existing project",
                ["Unit tests for the core logic", "Integration tests against a real database in a container",
                 "Coverage report and a failing-build threshold in CI", "One test that reproduces a past bug"],
                "coverage before and after, and CI run time"),
    "Security": ("Threat-model and harden one of your APIs",
                 ["Write a short threat model (OWASP Top 10 as the checklist)", "Fix what you find: authz checks, input validation, secrets, headers",
                  "Add dependency and static-analysis scanning to CI", "Write up each finding and fix"],
                 "findings fixed, by severity"),
    "Observability": ("Instrument one of your services with metrics, logs and traces",
                      ["Add OpenTelemetry tracing", "Expose Prometheus metrics for latency and errors",
                       "Build a Grafana dashboard and one alert", "Use it to find and fix a slow endpoint"],
                      "p95 latency before and after the fix you found"),
    "System Design": ("Write and build a design for a small high-traffic service",
                      ["Write a one-page design doc with trade-offs", "Build the core path with a queue and a cache",
                       "Load-test it", "Update the doc with what the test showed"],
                      "throughput and p95 latency at the limit"),
    "GCP": ("Deploy one of your projects to Google Cloud", ["Cloud Run service", "Cloud SQL database", "Secret Manager and IAM roles", "CI deploy on merge"],
            "cold-start time and monthly cost"),
    "Azure": ("Deploy one of your projects to Azure", ["App Service or Container Apps", "Azure SQL or PostgreSQL", "Key Vault and managed identity", "CI deploy on merge"],
              "deployment time and monthly cost"),
    "Kafka": ("Add an event stream to one of your projects", ["Run Kafka locally", "Publish domain events from your API", "Write a consumer with retries and a dead-letter topic",
                                                              "Show it surviving a consumer crash"], "messages per second, and recovery after a crash"),
}


# ---------------------------------------------------------------------------- measuring gaps
def gaps(db: DB, ctx: Context, limit: int = 8) -> tuple[list[Gap], int]:
    """Missing skills across the jobs you nearly match, most valuable first. Returns (gaps, jobs considered)."""
    thr = ctx.settings["scoring"]["shortlist_threshold"]
    have = {canonical(s.name) for s in ctx.profile.skills}
    rows = db.conn.execute("SELECT company, title, description, score, score_json, status FROM jobs WHERE score_json IS NOT NULL").fetchall()
    pool = []
    for r in rows:
        b = json.loads(r["score_json"])
        if b.get("blockers") or b.get("title", 0) < 0.5 or (r["score"] or 0) < thr - 15:
            continue
        pool.append((r, b))
    if len(pool) < MIN_JOBS:
        return [], len(pool)
    from .skills import extract_weighted

    count, required, employers, unlocks = Counter(), Counter(), defaultdict(list), Counter()
    for r, b in pool:
        weights = extract_weighted(f"{r['title']}\n{r['description'] or ''}")
        total_w = sum(weights.values()) or 1
        for skill, w in weights.items():
            if skill in have or w < 0.4:     # ignore skills only named in the company's intro
                continue
            count[skill] += 1
            required[skill] += w >= 1.0
            if r["company"] not in employers[skill]:
                employers[skill].append(r["company"])
            # would this job have reached the shortlist? skills are worth 35 points
            if (r["score"] or 0) < thr and (r["score"] or 0) + 35 * (w * 0.8) / total_w >= thr:
                unlocks[skill] += 1
    states = {r["skill"]: r["status"] for r in db.conn.execute("SELECT skill, status FROM projects")}
    out = [Gap(s, n / len(pool), n, required[s] / n, employers[s][:8], unlocks[s], states.get(s, ""))
           for s, n in count.items() if n / len(pool) >= 0.12]
    out.sort(key=lambda g: -(g.share * (0.6 + 0.4 * g.required_share) + 0.02 * g.unlocks))
    return out[:limit], len(pool)


def _snippets(db: DB, skill: str, limit: int = 5) -> list[str]:
    import re

    from .skills import _compiled
    pat = next((p for c, p in _compiled() if c == skill), None)
    out = []
    if not pat:
        return out
    for r in db.conn.execute("SELECT company, description FROM jobs WHERE score >= 40 AND description != '' ORDER BY score DESC LIMIT 300"):
        for line in (r["description"] or "").splitlines():
            if pat.search(line) and 30 < len(line) < 260:
                out.append(f"{r['company']}: {re.sub(r'^[-•* ]+', '', line.strip())}")
                break
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------- planning
def template_plan(ctx: Context, g: Gap) -> ProjectPlan:
    idea, steps, measure = IDEAS.get(g.skill, (
        f"Add {g.skill} to one of your existing projects in the way employers describe",
        [f"Work through the official {g.skill} getting-started guide", f"Use {g.skill} for one real feature of an existing project",
         "Write tests and a README section explaining your choices", "Publish it"], "one before-and-after result"))
    strong = [s.name for s in ctx.profile.skills if s.level >= 3][:4]
    chunks = ["Days 1-2", "Days 3-6", "Days 7-10", "Days 11-14"]
    return ProjectPlan(
        title=idea, one_line=idea + ".",
        why_this_project=f"{g.skill} appears in {g.share:.0%} of the jobs you nearly match "
                         f"({', '.join(g.employers[:4])}). This is the shortest honest route to listing it.",
        builds_on=strong,
        milestones=[Milestone(days=chunks[i] if i < len(chunks) else "Later", goal=step, tasks=[step]) for i, step in enumerate(steps)],
        definition_of_done=["It runs from a clean checkout using only the README", f"You measured {measure}",
                            "Someone else could review the repository and see how you used " + g.skill],
        what_to_publish=["Public repository", "README: what it does, how to run it, what you measured, what you'd do next",
                         "A short post or LinkedIn update about what you learned"],
        cv_bullets_when_done=[f"Built [project] using {g.skill}; [what you measured: {measure}]"],
        interview_talking_points=[f"Why you chose this approach to {g.skill}", "What went wrong and how you fixed it",
                                  "What you would change for production"],
        stretch_goals=["Add monitoring", "Write up one trade-off you had to make"],
        what_to_study_first=["The official getting-started guides for the tools named in the plan",
                             f"Two or three of the adverts that ask for {g.skill}: note exactly what they expect"],
    )


def plan(db: DB, ctx: Context, llm: Optional[LLM], g: Gap, say=print) -> Path:
    p: Optional[ProjectPlan] = None
    if llm is not None:
        try:
            p = llm.structured(
                system=system_prompt(ctx.profile, ctx.cv, "a senior engineer who mentors people into UK tech jobs"),
                prompt=PLAN_TASK.format(skill=g.skill, share=g.share, jobs=g.jobs, required=g.required_share,
                                        employers=", ".join(g.employers) or "various",
                                        snippets="\n".join(f"- {s}" for s in _snippets(db, g.skill)) or "- (no quotes found)"),
                schema=ProjectPlan, effort=ctx.settings["llm"]["tailor_effort"])
        except LLMError as e:
            say(f"  Claude failed ({e}); using the template plan")
    if p is None:
        p = template_plan(ctx, g)
    d = OUTPUT_DIR / "projects"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{slug(g.skill)}.md"
    path.write_text(plan_markdown(g, p), encoding="utf-8")
    db.conn.execute("INSERT INTO projects (skill, status, created_at, plan_path, demand) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(skill) DO UPDATE SET plan_path=excluded.plan_path, demand=excluded.demand, "
                    "status=CASE WHEN projects.status IN ('done','in_progress') THEN projects.status ELSE 'planned' END",
                    (g.skill, "planned", now_iso(), str(path), g.share))
    db.commit()
    return path


def plan_markdown(g: Gap, p: ProjectPlan) -> str:
    o = [f"# Project: {p.title}", "", f"Skill: **{g.skill}**. Planned {date.today():%d %B %Y}.", "", p.one_line, "",
         "## Why", "", p.why_this_project, "",
         f"- Asked for in {g.share:.0%} of the jobs you nearly match ({g.jobs} adverts), a requirement in {g.required_share:.0%} of those",
         f"- Employers: {', '.join(g.employers)}"]
    if g.unlocks:
        o.append(f"- {g.unlocks} current near-miss jobs would reach your shortlist with it")
    o += ["", "Builds on what you know: " + ", ".join(p.builds_on), "", "## Study first", ""] + [f"- {x}" for x in p.what_to_study_first]
    o += ["", "## Two-week plan", ""]
    for m in p.milestones:
        o += [f"### {m.days}: {m.goal}", ""] + [f"- [ ] {t}" for t in m.tasks] + [""]
    o += ["## Done means", ""] + [f"- [ ] {x}" for x in p.definition_of_done]
    o += ["", "## Publish", ""] + [f"- [ ] {x}" for x in p.what_to_publish]
    o += ["", "## When it's finished", "",
          f"Run `jobstream grow --done \"{g.skill}\"`. It shows what to paste into your profile and master CV.", "",
          "CV bullets (fill in the [placeholders] with what you really measured):", ""] + [f"- {x}" for x in p.cv_bullets_when_done]
    o += ["", "## Interview talking points", ""] + [f"- {x}" for x in p.interview_talking_points]
    o += ["", "## Stretch goals", ""] + [f"- {x}" for x in p.stretch_goals]
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------------------- tracking
def set_status(db: DB, skill: str, status: str) -> Optional[str]:
    row = db.conn.execute("SELECT skill FROM projects WHERE lower(skill)=lower(?)", (skill,)).fetchone()
    if not row:
        return None
    db.conn.execute("UPDATE projects SET status=?, done_at=CASE WHEN ?='done' THEN ? ELSE done_at END WHERE skill=?",
                    (status, status, now_iso(), row[0]))
    db.commit()
    return row[0]


def done_snippet(skill: str) -> str:
    return f"""Well done. Now tell the agent, so every future CV and score includes it.

1) In config/profile.yaml, under `skills:`, add:

  - {{name: {skill}, years: 0.1, level: 2}}

2) In config/cv_master.yaml, under `projects:`, add (with your real repository and results):

  - name: <your project name>
    link: https://github.com/<you>/<repo>
    description: <one sentence: what you built with {skill} and what you measured>
    tags: [{skill.lower()}, <other tech you used>]

3) Run `jobstream search` to re-score your jobs with the new skill."""


def active(db: DB) -> list:
    return db.conn.execute("SELECT * FROM projects WHERE status IN ('planned','in_progress') ORDER BY created_at").fetchall()
