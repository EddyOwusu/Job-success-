from datetime import datetime, timezone

from jobagent.matching import detect_level, quick_title_filter, score_job
from jobagent.models import Job
from jobagent.skills import extract_skills, extract_weighted
from jobagent.sources.base import is_uk
from jobagent.sponsors import Sponsor

SP = Sponsor("Acme Ltd", "London", "", "Worker (A rating)", "Skilled Worker")
DESC = """About the role
We build payments APIs.
Requirements
- 3+ years of Python and Django
- PostgreSQL, Docker, AWS
Nice to have
- Kubernetes
Salary: £50,000 - £65,000. We offer visa sponsorship."""


def job(**kw):
    base = dict(source="greenhouse", source_id="1", company="Acme", title="Backend Engineer", location="London, UK",
                description=DESC, salary_min=50000, salary_max=65000, posted_at=datetime.now(timezone.utc))
    base.update(kw)
    return Job(**base)


def test_good_match_scores_high(profile, settings):
    b = score_job(job(), profile, settings, SP)
    assert b.total >= 75, b
    assert not b.blockers
    assert {"Python", "Django", "PostgreSQL"} <= set(b.matched_skills)
    assert "Kubernetes" in b.missing_skills


def test_no_sponsorship_is_blocked(profile, settings):
    b = score_job(job(description=DESC + "\nWe are unable to offer visa sponsorship."), profile, settings, SP)
    assert b.blockers and b.total <= 20


def test_unregistered_employer_blocked(profile, settings):
    b = score_job(job(description=DESC.replace("We offer visa sponsorship.", "")), profile, settings, None)
    assert any("register" in x for x in b.blockers)


def test_low_salary_blocked(profile, settings):
    b = score_job(job(salary_min=28000, salary_max=32000), profile, settings, SP)
    assert any("threshold" in x for x in b.blockers)


def test_seniority_penalty(profile, settings):
    mid = score_job(job(), profile, settings, SP).total
    staff = score_job(job(title="Staff Backend Engineer"), profile, settings, SP).total
    assert staff < mid - 10


def test_levels():
    assert detect_level("Senior Software Engineer") == "senior"
    assert detect_level("Graduate Developer") == "graduate"
    assert detect_level("Software Engineer") is None


def test_skill_extraction():
    s = extract_skills("Go to the office. Experience with (Go, Java) and k8s, Postgres, rest of the team")
    assert {"Go", "Java", "Kubernetes", "PostgreSQL"} <= s
    assert "REST APIs" not in s
    w = extract_weighted(DESC)
    assert w["Python"] == 1.0 and w["Kubernetes"] == 0.4


def test_title_filter(profile):
    want = quick_title_filter(profile)
    assert want("Senior Python Developer")
    assert want("Backend Engineer, Payments")
    assert not want("Sales Director")
    assert not want("Account Executive")


def test_is_uk():
    assert is_uk("London, England, GB")
    assert is_uk("Remote (UK)")
    assert not is_uk("New York, NY")
    assert not is_uk("Cambridge, MA")
    assert is_uk("New York, NY; London, UK")
    assert not is_uk("Remote; Europe; European Union; Poland")
