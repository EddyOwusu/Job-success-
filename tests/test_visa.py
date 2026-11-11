import pytest

from jobstream.visa import clearance_required, parse_salary, salary_check, sponsorship_signal


@pytest.mark.parametrize("text,label", [
    ("We’re unable to support relocation or visa sponsorship for this role.", "negative"),
    ("Visa sponsorship is not available.", "negative"),
    ("Unfortunately we cannot offer sponsorship.", "negative"),
    ("We do not provide visa sponsorship", "negative"),
    ("We offer visa sponsorship and relocation support.", "positive"),
    ("We can sponsor Skilled Worker visas.", "positive"),
    ("You must have the right to work in the UK.", "weak_negative"),
    ("Join our friendly team!", "neutral"),
    ("Visa sponsorship: We do sponsor visas! However, we aren't able to successfully sponsor visas for every role "
     "and every candidate.", "positive"),
    ("At this time, we are unable to provide visa sponsorship for this role.", "negative"),
])
def test_sponsorship_signal(text, label):
    assert sponsorship_signal(text).label == label


def test_clearance():
    assert clearance_required("Candidates must hold active SC clearance")
    assert not clearance_required("We build clear APIs")


@pytest.mark.parametrize("text,expected", [
    ("Salary: £45,000 - £60,000 per annum", (45000, 60000)),
    ("£50k-£65k + equity", (50000, 65000)),
    ("Starting salary: £68,000 - £87,500", (68000, 87500)),
    ("£550 per day", (None, None)),
    ("competitive", (None, None)),
])
def test_parse_salary(text, expected):
    assert parse_salary(text) == expected


def test_salary_check(settings):
    assert salary_check(30000, 35000, settings, False).status == "below"
    assert salary_check(30000, 35000, settings, True).status == "ok"
    assert salary_check(None, None, settings, False).status == "unknown"
    assert salary_check(45000, 60000, settings, False).status == "ok"


def test_transitional_rules_for_people_already_sponsored(settings):
    from types import SimpleNamespace as V

    from jobstream.visa import threshold_for, transitional

    early = V(first_cos_date="2022-11", continuous_since_first_cos=True, new_entrant=False)
    assert transitional(early) == {"lower_salary": True, "medium_skilled": True}
    assert threshold_for(early, settings)[0] == 31300
    assert salary_check(32000, 34000, settings, early).status == "ok"          # blocked for a new applicant
    assert salary_check(28000, 30000, settings, early).status == "below"
    mid = V(first_cos_date="2024-09-15", continuous_since_first_cos=True, new_entrant=False)
    assert transitional(mid) == {"lower_salary": False, "medium_skilled": True}
    assert threshold_for(mid, settings)[0] == 41700
    broken = V(first_cos_date="2022-11-01", continuous_since_first_cos=False, new_entrant=False)
    assert transitional(broken) == {"lower_salary": False, "medium_skilled": False}
    assert threshold_for(V(first_cos_date=None, continuous_since_first_cos=False, new_entrant=True), settings)[0] == 33400
