"""Prompts. The candidate dossier goes in the system prompt so it is cached across jobs."""
from __future__ import annotations

import yaml

from .models import Job, MasterCV, Profile

TRUTH_RULES = """\
Ground rules, which matter more than anything else here:
- Use only facts in the candidate dossier. Never invent employers, dates, titles, degrees,
  certifications, metrics, skills or achievements. If the dossier doesn't say it, the candidate
  didn't do it.
- You may rephrase, reorder, merge and shorten the candidate's facts, and use the advert's own
  vocabulary for things the candidate genuinely did (e.g. "REST APIs" for "HTTP JSON endpoints").
- Never add hidden text, keyword lists in white font or anything that tricks an ATS. Beat the
  ATS by being relevant and readable: standard headings, the advert's exact skill names where
  true, and no tables, columns, images or icons.
- Right-to-work and visa answers must state the candidate's real situation exactly as given.
"""


def dossier(profile: Profile, cv: MasterCV) -> str:
    p = profile.model_dump(exclude={"standard_answers"})
    return (
        "<candidate_profile>\n" + yaml.safe_dump(p, sort_keys=False, allow_unicode=True) + "</candidate_profile>\n"
        "<master_cv>\n" + yaml.safe_dump(cv.model_dump(), sort_keys=False, allow_unicode=True) + "</master_cv>"
    )


def system_prompt(profile: Profile, cv: MasterCV, role: str) -> str:
    return f"""You are {role} working for one candidate: {profile.personal.full_name}.
Their goal is a tech job in the UK with a sponsor licence holder who will sponsor a
{profile.visa.target_route} visa. Every hour they spend on the wrong application is lost, so
be honest and specific. Write in {profile.writing.spelling}.

{TRUTH_RULES}
{dossier(profile, cv)}"""


def _agency_note(job: Job) -> str:
    from .agencies import is_agency
    if is_agency(job.company, job.extra):
        return ("\nPosted by a recruitment agency: the hiring company is not named, so whether it can sponsor is "
                "unknown until the recruiter confirms the client.")
    return ""


def job_block(job: Job, sponsor_name: str | None, extra: str = "") -> str:
    salary = ""
    if job.salary_min or job.salary_max:
        salary = f"£{job.salary_min or '?'} - £{job.salary_max or '?'}"
    return f"""<job>
Company: {job.company}
Title: {job.title}
Location: {job.location} ({job.remote or 'work mode not stated'})
Salary: {salary or 'not stated'}
On the UK Skilled Worker sponsor register as: {sponsor_name or 'NOT FOUND on the register'}{_agency_note(job)}
URL: {job.url}

{job.description[:20000]}
</job>
{extra}"""


ASSESS_RULES = 2          # bump when the assessment rules change; `assess --again` redoes older ones

ASSESS_TASK = """Assess this job for the candidate.

Think like an experienced UK tech recruiter. Consider:
- Hard requirements the candidate clearly meets or misses (years, languages, domain).
- Whether this employer is likely to sponsor THIS role: register status, wording in the advert,
  seniority (graduate roles at big firms often sponsor; small agencies rarely do), and whether the
  salary can clear the Skilled Worker threshold of £{threshold:,} (new entrant: £{new_entrant:,}).
- Security clearance, "UK nationals only" or onsite-at-client wording, which usually rule out
  sponsored candidates.
- How strong the candidate looks against the likely applicant pool.

How to judge some common cases:
- Silence on sponsorship is normal: most UK adverts never mention it. If the employer is on the register and
  the advert doesn't rule sponsorship out, that is a neutral point, not a gap. Say "ask HR early" once at most.
- Salary: if the top of the band (or a single stated figure) reaches the candidate's floor, the job is viable;
  the candidate asks for at least the floor. Only count salary against the job when the whole band is below it.
  Adzuna figures with pennies or identical min and max are estimates: treat salary as not stated.
- A short or cut-off advert is a gap in the data, not in the candidate: judge on what is there.
- Do not list location, distance from the candidate's current town or onsite work as a weakness when the
  candidate will relocate (see the note below). Driving licences, travel between sites and on-call are fine to
  mention only if the advert asks for them.

fit_score (0-100) is how worthwhile this application is for this candidate, given the roles a sponsored
candidate can realistically get. Use the whole scale:
  85+  meets every essential requirement, the employer can sponsor, the salary clears the floor: apply today
  70-84 meets most essentials; a good CV and a message to the hiring team give a real chance
  50-69 workable but with a clear gap (a missing essential skill, an uncertain sponsor, a weak salary)
  under 50 a long shot, or sponsorship looks unlikely
verdict: "apply" (strong), "apply_with_networking" (decent, needs a referral or a message to stand
out), "stretch" (long shot), "skip" (not worth the time, or sponsorship is very unlikely).
gaps and red_flags: only real problems, most serious first. Do not repeat a point in both lists.
keywords_to_mirror: exact phrases from the advert that the candidate can truthfully use.
"""

TAILOR_TASK = """Write a tailored, ATS-friendly CV for this job.

- headline: the advert's job title or the closest truthful version of it.
- summary: 3 sentences. Lead with the most relevant experience for THIS job, using the
  advert's language where it is true. No clichés ("passionate", "results-driven", "team player").
- skills: 10-18 skills from the dossier, most relevant to the advert first, using the advert's
  spelling (e.g. "PostgreSQL" vs "Postgres") when it is the same thing.
- experience: every role from the master CV, in the same order, with the same company, title and
  dates. Choose and rewrite 3-6 bullets per recent role (fewer for older roles): strongest
  evidence for this job first, start each with a verb, keep the numbers. Roles marked
  kind: other are listed in a brief "Other employment" section: give them no bullets, or one
  short bullet only when the role is directly relevant to this job.
- projects: 0-3 one-line entries, only if they help for this job.
- education / certifications: as in the dossier, one line each.
Keep it to what fits on two A4 pages.

Talking points from the fit assessment, use them where they are true:
{talking_points}
Keywords to mirror where they are true:
{keywords}
"""

COVER_TASK = """Write a cover letter for this job, at most {max_words} words.

- greeting: "Dear Hiring Team," unless the advert names a person.
- 3-4 short paragraphs: (1) the role, and one specific, real reason this company or its product
  appeals (taken from the advert); (2) and (3) two or three pieces of hard evidence from the
  dossier that map to the advert's top requirements; (4) a confident close. Mention the visa only
  if the advert raises it, and then briefly and positively ("I would need Skilled Worker
  sponsorship; I'm a straightforward case: ...") using only true facts.
- sign_off: "Kind regards,\\n{name}"
Tone: {tone}.
"""

ANSWERS_TASK = """Answer these questions from the job's application form for the candidate.

Rules:
- Use the candidate's standard answers when a question matches one of them:
{standard_answers}
- Visa and right-to-work questions must match the candidate's visa section exactly. For
  "Do you require sponsorship?" the honest answer is "{needs_sponsorship}".
- For select fields, the answer must be exactly one of the listed option labels.
- For free-text questions ("Why do you want to work here?") write 60-150 words of specific,
  truthful content from the dossier and the advert.
- If you cannot answer truthfully from the dossier (e.g. "Do you hold an active DV clearance?"
  with no information), give your best honest answer, set confidence "low" and needs_human true.
- Demographic or diversity questions: use the standard answer, or "Prefer not to say" / "I don't
  wish to answer" if there is such an option.

<questions>
{questions}
</questions>
"""

STATEMENT_TASK = """This employer shortlists by scoring a supporting statement against the person
specification, criterion by criterion. Write it for the candidate.

- First, list every Essential and Desirable criterion from the advert and, for each, say whether
  the candidate meets it (yes / partly / no) with the single best truthful example from the dossier.
  Use the STAR shape (situation, task, action, result) in one or two sentences.
- Then write the statement (600-900 words): a short opening on why this role and this
  organisation (use the advert: its mission, patients, students or users), then paragraphs that
  follow the order of the person specification, naming each criterion's words so a shortlister can
  tick it off. Essential criteria first. For a "partly" or "no", show the closest transferable
  evidence and how the candidate would close the gap; never claim it is met.
- Close with availability and, only if relevant, a one-line, positive note on sponsorship.
"""

OUTREACH_TASK = """Plan the networking for this application, so the candidate is not just one more
CV in the pile.

- people_to_find: 3-5 job titles at {company} worth contacting, most useful first (e.g. the
  likely hiring manager for this team, an engineer on the team, a technical recruiter, a recent
  hire who also moved to the UK on a visa).
- messages (all short, specific, human, in {spelling}; never grovelling, never generic):
  1. linkedin_connection to the hiring manager, at most 280 characters, day 0
  2. linkedin_message to a recruiter at the company, about 80 words: mention the application, one
     piece of evidence, and politely confirm they sponsor Skilled Worker visas for this role, day 0
  3. referral_ask to an engineer on the team, about 80 words: a real question about their work
     first, then the ask, day 1-2
  4. follow_up_email to the recruiter, about 90 words, day 5-7
  5. follow_up_email second nudge, about 50 words, day 12-14
  Use placeholders like [First name] for names you do not know.
- tips: 3-5 concrete, company-specific ideas (e.g. a meetup they host, their engineering blog,
  an open-source repo to contribute to, how to word the visa question).
"""
