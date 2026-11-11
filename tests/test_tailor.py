from jobstream.apply.answers import classify, pick_option, rule_based_answers
from jobstream.config import Context
from jobstream.models import Job, TailoredCV, TailoredRole
from jobstream.tailor import guard, keyword_tailor


def test_guard_removes_invented_facts(profile, cv):
    t = TailoredCV(
        headline="Backend Engineer", summary="Backend engineer with 4 years of experience.",
        skills=["Python", "Kubernetes", "Django"],
        experience=[
            TailoredRole(company="Example Fintech Ltd", title="Principal Engineer", location="", start="2020-01",
                         end="present", bullets=["Built Django REST microservices handling 2M+ requests/day",
                                                 "Grew revenue by 300% in 6 months"]),
            TailoredRole(company="Made Up Corp", title="CTO", location="", start="", end="", bullets=["Led everything"]),
        ],
        projects=[], education=["BSc Computer Science (First Class), University of Example"],
        certifications=["Google Professional Cloud Architect"],
    )
    out, warnings = guard(t, profile, cv)
    assert "Kubernetes" not in out.skills and "Python" in out.skills
    companies = [r.company for r in out.experience]
    assert "Made Up Corp" not in companies
    assert companies == [r.company for r in cv.experience]       # all real roles kept, in order
    first = out.experience[0]
    assert first.title == "Software Engineer" and first.start == "2023-01"   # dates/titles restored
    assert all("300%" not in b for b in first.bullets)
    assert out.certifications == []
    assert len(warnings) >= 4


def test_keyword_tailor_orders_by_relevance(profile, cv, settings):
    ctx = Context(profile, cv, settings)
    j = Job(source="x", source_id="1", company="A", title="Data Engineer",
            description="Requirements\n- ETL pipelines in SQL and Python\n- Airflow")
    out = keyword_tailor(ctx, j)
    assert out.skills[0] in ("Python", "SQL")
    assert "ETL" in out.experience[1].bullets[0]


def test_answers(profile, cv, settings):
    ctx = Context(profile, cv, settings)
    assert classify("Full name ✱") == "full_name"
    assert classify("Will you now or in the future require visa sponsorship?") == "needs_sponsorship"
    assert pick_option("Yes", ["Yes", "No"]) == "Yes"
    assert pick_option("Prefer not to say", ["Man", "Woman", "I don't wish to answer"]) == "I don't wish to answer"
    fa = rule_based_answers(ctx, [
        {"label": "Do you require sponsorship?", "required": True, "options": ["Yes", "No"]},
        {"label": "Are you legally authorised to work in the UK?", "required": True, "options": ["Yes", "No"]},
        {"label": "Describe your favourite algorithm", "required": True},
    ])
    assert fa.answers[0].answer == "Yes"
    assert fa.answers[1].answer == "No"
    assert fa.answers[2].needs_human


def test_guard_keeps_honest_variants_of_your_skills(profile, cv):
    skills = [s.name for s in profile.skills]
    assert "Python" in skills and "AWS" in skills
    t = TailoredCV(headline="Backend Engineer", summary="Building Python services since 2021.",
                   skills=["Python (Django, FastAPI)", "AWS (cloud)", "Kubernetes (EKS)", "Python (Kubernetes)"],
                   experience=[], projects=[], education=[], certifications=[])
    t, warnings = guard(t, profile, cv)
    assert t.skills == ["Python (Django, FastAPI)", "AWS (cloud)"]
    assert t.summary == "Building Python services since 2021."          # "2021." is the year 2021
    assert any("Kubernetes (EKS)" in w for w in warnings)
