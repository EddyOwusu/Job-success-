from jobstream.sources import reed


def test_reed_uses_yearly_salary_and_external_link(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, auth=None, **kw):
        calls.append((url, params, auth))
        if url.endswith("/search"):
            return {"results": [{"jobId": 55, "employerName": "Acme Ltd", "jobTitle": "Python Developer",
                                 "locationName": "Leeds", "minimumSalary": 450, "maximumSalary": 500,
                                 "date": "09/11/2026", "jobDescription": "snippet", "jobUrl": "https://www.reed.co.uk/jobs/55"},
                                {"jobId": 56, "employerName": "B", "jobTitle": "Sales Manager", "jobUrl": "u"}]}
        return {"jobDescription": "<p>Full <b>advert</b></p>", "yearlyMinimumSalary": 117000, "yearlyMaximumSalary": 130000,
                "externalUrl": "https://acme.example/apply", "contractType": "contract", "salaryType": "per day"}

    monkeypatch.setenv("REED_API_KEY", "test-key")
    monkeypatch.setattr(reed, "get_json", fake_get_json)
    stats = {}
    jobs = reed.search("python developer", "Leeds", want=lambda t: "developer" in t.lower(), known={"99"}, stats=stats)
    assert stats["seen"] == 2 and len(jobs) == 1
    j = jobs[0]
    assert (j.salary_min, j.salary_max) == (117000, 130000)          # not the 450-500 day rate
    assert j.apply_url == "https://acme.example/apply" and j.url.endswith("/55")
    assert j.description == "Full advert" and j.posted_at.year == 2026 and j.extra["contract"] == "contract"
    # the key goes in the basic-auth username with an empty password, as Reed's documentation requires
    assert calls[0][2] == ("test-key", "") and calls[0][1]["locationName"] == "Leeds"
