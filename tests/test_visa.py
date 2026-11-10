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
    assert salary_check(30000, 35000, settings, new_entrant=False).status == "below"
    assert salary_check(30000, 35000, settings, new_entrant=True).status == "ok"
    assert salary_check(None, None, settings, new_entrant=False).status == "unknown"
    assert salary_check(45000, 60000, settings, new_entrant=False).status == "ok"
