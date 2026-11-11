"""Data models for the profile, master CV, jobs and generated content."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- profile
class Personal(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    pronouns: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Targets(BaseModel):
    roles: list[str]
    seniority: list[str] = Field(default_factory=lambda: ["mid"])
    years_experience: float = 0
    locations: list[str] = Field(default_factory=lambda: ["London"])
    remote_ok: bool = True
    hybrid_ok: bool = True
    onsite_ok: bool = True
    min_salary_gbp: int = 0
    search_queries: list[str] = Field(default_factory=list)
    exclude_title_words: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    dream_companies: list[str] = Field(default_factory=list)

    @property
    def anywhere(self) -> bool:
        """True when the person will work anywhere in the UK ("Anywhere in the UK" in locations, or none listed)."""
        places = [l for l in self.locations if "remote" not in l.lower()]
        return not places or any("anywhere" in l.lower() for l in places)


class Skill(BaseModel):
    name: str
    years: float = 0
    level: int = 2


class Education(BaseModel):
    highest_level: str = "bachelors"
    degree: str = ""
    institution: str = ""
    graduation_year: Optional[int] = None
    graduation_month: Optional[int] = None   # 1-12, helps pick the right HPI university list
    country: str = ""                        # where the university is
    uk_degree: bool = False


class Visa(BaseModel):
    needs_sponsorship: bool = True
    current_uk_right_to_work: bool = False   # e.g. True while on a Graduate visa
    date_of_birth: Optional[str] = None      # YYYY-MM-DD, only used to check under-26 rules
    had_graduate_visa: bool = False
    target_route: str = "Skilled Worker"
    current_status: str = ""
    nationality: str = ""
    new_entrant: bool = False
    # Already on the Skilled Worker route? These unlock gov.uk's transitional rules.
    first_cos_date: Optional[str] = None            # YYYY-MM-DD (or YYYY-MM) of your FIRST certificate of sponsorship
    continuous_since_first_cos: bool = False        # held Skilled Worker visas without a break since then
    earliest_start: str = ""
    willing_to_relocate: bool = True
    skip_security_clearance_roles: bool = True


class Writing(BaseModel):
    tone: str = "confident, warm, specific"
    spelling: str = "British English"
    cover_letter_max_words: int = 300


class Profile(BaseModel):
    personal: Personal
    targets: Targets
    skills: list[Skill] = Field(default_factory=list)
    education: Education = Field(default_factory=Education)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    visa: Visa = Field(default_factory=Visa)
    standard_answers: dict[str, str] = Field(default_factory=dict)
    writing: Writing = Field(default_factory=Writing)

    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]


# --------------------------------------------------------------------------- master CV
class Bullet(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)


class Role(BaseModel):
    company: str
    title: str
    kind: str = "main"       # "other" = listed briefly under "Other employment"
    location: str = ""
    start: str = ""
    end: str = "present"
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    link: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str
    institution: str = ""
    year: Optional[int | str] = None
    details: str = ""


class Story(BaseModel):
    title: str
    text: str


class MasterCV(BaseModel):
    headline: str = ""
    summary: str = ""
    experience: list[Role] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)


# --------------------------------------------------------------------------- jobs
class Job(BaseModel):
    """A normalised job posting from any source."""

    source: str                       # greenhouse | lever | ashby | reed | adzuna | ...
    source_id: str                    # id inside the source
    company: str
    title: str
    location: str = ""
    url: str = ""
    apply_url: str = ""
    description: str = ""             # plain text
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = "GBP"
    remote: Optional[str] = None      # remote | hybrid | onsite | None
    posted_at: Optional[datetime] = None
    ats: Optional[str] = None         # greenhouse | lever | ashby | None
    ats_token: Optional[str] = None   # board token, e.g. "monzo"
    extra: dict = Field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"


class ScoreBreakdown(BaseModel):
    total: float
    skills: float
    title: float
    seniority: float
    location: float
    salary: float
    sponsorship: float
    freshness: float
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    scaleup: bool = False             # employer holds a Scale-up sponsor licence


# --------------------------------------------------------------------------- LLM outputs
class FitAssessment(BaseModel):
    """Claude's deep read of a job against the candidate."""

    fit_score: int = Field(description="0-100: how likely this candidate gets an interview")
    verdict: str = Field(description="apply | apply_with_networking | stretch | skip")
    sponsorship_likelihood: str = Field(description="high | medium | low | none")
    sponsorship_evidence: str
    salary_meets_visa_threshold: str = Field(description="yes | no | unknown")
    seniority_match: str
    strengths: list[str]
    gaps: list[str]
    red_flags: list[str]
    talking_points: list[str] = Field(description="Specific angles to stress in CV, cover letter and outreach")
    keywords_to_mirror: list[str] = Field(description="Exact phrases from the advert the CV should use, only where truthful")


class TailoredRole(BaseModel):
    company: str
    title: str
    location: str
    start: str
    end: str
    bullets: list[str]
    kind: str = "main"


class TailoredCV(BaseModel):
    headline: str
    summary: str
    skills: list[str] = Field(description="Ordered most relevant first; ONLY skills present in the source material")
    experience: list[TailoredRole]
    projects: list[str]
    education: list[str]
    certifications: list[str]


class CoverLetter(BaseModel):
    greeting: str
    paragraphs: list[str]
    sign_off: str


class FormAnswer(BaseModel):
    question: str
    answer: str
    confidence: str = Field(description="high | medium | low; low means a human must check it")
    needs_human: bool


class FormAnswers(BaseModel):
    answers: list[FormAnswer]


class CriterionEvidence(BaseModel):
    criterion: str
    met: str = Field(description="yes | partly | no")
    evidence: str = Field(description="Specific, truthful example from the dossier (STAR style), or how the gap is covered")


class SupportingStatement(BaseModel):
    """NHS / university / public-sector style statement, scored criterion by criterion."""
    criteria: list[CriterionEvidence]
    statement: str = Field(description="The full supporting statement, 600-900 words, in paragraphs")


class OutreachMessage(BaseModel):
    channel: str = Field(description="linkedin_connection | linkedin_message | email | follow_up_email | referral_ask")
    target: str = Field(description="Who it is for, e.g. 'Hiring manager', 'Recruiter', 'Engineer on the team'")
    subject: str
    body: str
    send_on: str = Field(description="When to send relative to the application, e.g. 'day 0', 'day 3', 'day 7'")


class OutreachPlan(BaseModel):
    people_to_find: list[str] = Field(description="Job titles of people at this company worth contacting, most useful first")
    messages: list[OutreachMessage]
    tips: list[str]
