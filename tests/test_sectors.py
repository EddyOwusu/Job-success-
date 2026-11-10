from jobstream.cli import parse_board_url
from jobstream.models import Job
from jobstream.sources.nhs import _salary
from jobstream.tailor import needs_statement
from jobstream.visa import sponsorship_signal
from jobstream.matching import quick_title_filter


def test_nhs_salary():
    assert _salary("£57528.00 to £64750.00") == (57528.0, 64750.0)
    assert _salary("Depending on experience") == (None, None)


def test_public_sector_sponsorship_wording():
    nhs = ("Applications from job seekers who require current Skilled worker sponsorship to work in the UK "
           "are welcome and will be considered alongside all other applications.")
    assert sponsorship_signal(nhs).label == "positive"
    assert sponsorship_signal("This post is not eligible for sponsorship.").label == "negative"
    assert sponsorship_signal("This role is eligible for sponsorship under the Skilled Worker route.").label == "positive"
    assert sponsorship_signal("If you do not have the right to work, we are able to sponsor.").label == "positive"


def test_statement_detection():
    assert needs_statement(Job(source="nhs", source_id="1", company="Trust", title="Developer", extra={"sector": "nhs"}))
    assert needs_statement(Job(source="workday", source_id="1", company="X", title="Dev",
                               description="Please address the essential criteria in your supporting statement"))
    assert not needs_statement(Job(source="greenhouse", source_id="1", company="X", title="Dev", description="Join us"))


def test_board_urls():
    assert parse_board_url("https://lbg.wd3.myworkdayjobs.com/en-GB/LBG_Careers/job/x") == ("workday", "lbg.wd3.myworkdayjobs.com|LBG_Careers")
    assert parse_board_url("https://boards.greenhouse.io/monzo") == ("greenhouse", "monzo")
    assert parse_board_url("https://example.com") == (None, None)


def test_non_tech_titles(profile):
    want = quick_title_filter(profile)
    for t in ["Senior Systems Developer", "Integration Developer", "Research Software Engineer", "IT Application Developer",
              "Digital Developer (Band 6)"]:
        assert want(t), t
    assert not want("Staff Nurse")


def test_abroad_filter():
    from jobstream.sources.base import abroad
    assert abroad("Dubai Emirates Aviation University")
    assert abroad("Ningbo, China University of Nottingham")
    assert not abroad("Rotherham, Hybrid")
    assert not abroad("Dublin, Ireland; London, UK")
