"""ATS keyword coverage: how well a CV covers the advert's skills, and what is genuinely missing."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Profile, TailoredCV
from .skills import canonical, extract_skills, extract_weighted


@dataclass
class ATSReport:
    coverage: float                                   # 0-1, weighted by required/nice-to-have
    present: list[str] = field(default_factory=list)
    missing_but_true: list[str] = field(default_factory=list)   # you have it, CV doesn't say it: fix
    genuine_gaps: list[str] = field(default_factory=list)        # you don't have it: learn or explain

    def summary(self) -> str:
        s = f"ATS keyword coverage {self.coverage:.0%}."
        if self.missing_but_true:
            s += f" Add (you have these): {', '.join(self.missing_but_true)}."
        if self.genuine_gaps:
            s += f" Gaps: {', '.join(self.genuine_gaps)}."
        return s


def cv_text(cv: TailoredCV) -> str:
    parts = [cv.headline, cv.summary, ", ".join(cv.skills)]
    for r in cv.experience:
        parts += [r.title, *r.bullets]
    parts += cv.projects + cv.education + cv.certifications
    return "\n".join(parts)


def check(job_text: str, cv: TailoredCV, profile: Profile) -> ATSReport:
    wanted = extract_weighted(job_text)
    if not wanted:
        return ATSReport(1.0)
    have_in_cv = extract_skills(cv_text(cv)) | {canonical(s) for s in cv.skills}
    have_at_all = {canonical(s.name) for s in profile.skills}
    total = sum(wanted.values())
    got = sum(w for k, w in wanted.items() if k in have_in_cv)
    order = sorted(wanted, key=lambda k: -wanted[k])
    return ATSReport(
        coverage=got / total,
        present=[k for k in order if k in have_in_cv],
        missing_but_true=[k for k in order if k not in have_in_cv and k in have_at_all],
        genuine_gaps=[k for k in order if k not in have_in_cv and k not in have_at_all],
    )
