from jobagent.sponsors import from_csv_text

CSV = """Organisation Name,Town/City,County,Type & Rating,Route
Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker
Roofoods Ltd t/a Deliveroo,London,,Worker (A rating),Skilled Worker
Maxico Uk limited t/a The Amazon,Leeds,,Worker (A rating),Skilled Worker
Amazon UK Services Ltd.,London,,Worker (A rating),Skilled Worker
Eleven Labs Ltd,London,,Worker (A rating),Skilled Worker
Trainline.com Ltd,London,,Worker (A rating),Skilled Worker
STRIPE CONSULTING LIMITED,HORLEY,,Worker (A rating),Skilled Worker
Stripe Payments UK Ltd,London,,Worker (A rating),Skilled Worker
Some Church,York,,Worker (A rating),Tier 2 Ministers of Religion
Facebook UK,London,,Worker (A rating),Skilled Worker
"""


def test_matches_brand_to_legal_name():
    reg = from_csv_text(CSV)
    assert reg.match("Monzo").name == "Monzo Bank Ltd"
    assert reg.match("Deliveroo").name == "Roofoods Ltd t/a Deliveroo"
    assert reg.match("ElevenLabs").name == "Eleven Labs Ltd"
    assert reg.match("Trainline").name == "Trainline.com Ltd"
    assert reg.match("Stripe").name == "Stripe Payments UK Ltd"


def test_prefers_legal_name_over_trading_name():
    assert from_csv_text(CSV).match("Amazon").name == "Amazon UK Services Ltd."


def test_unknown_and_other_routes():
    reg = from_csv_text(CSV)
    assert reg.match("Totally Unknown Startup") is None
    assert reg.match("Some Church") is None  # not a Skilled Worker sponsor


def test_aliases():
    from jobagent.sponsors import SponsorRegister
    import csv, io
    reg = SponsorRegister(csv.DictReader(io.StringIO(CSV)), aliases={"Meta": "Facebook UK"})
    assert reg.match("Meta").name == "Facebook UK"
