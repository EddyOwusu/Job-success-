import json
import types

import pytest

from jobstream import pipeline
from jobstream.config import Context
from jobstream.db import DB
from jobstream.models import FitAssessment, Job
from jobstream.spend import Ledger


def _fit(score, verdict="apply"):
    return FitAssessment(fit_score=score, verdict=verdict, sponsorship_likelihood="high", sponsorship_evidence="",
                         salary_meets_visa_threshold="yes", seniority_match="ok", strengths=["s"], gaps=[],
                         red_flags=[], talking_points=[], keywords_to_mirror=[])


class FakeBatches:
    """Stands in for client.messages.batches: answers each job with a score, after one 'in progress' check."""
    def __init__(self, scores):
        self.scores, self.created, self.checks = scores, [], 0

    def create(self, requests):
        self.created.append(requests)
        return types.SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id):
        self.checks += 1
        return types.SimpleNamespace(processing_status="in_progress" if self.checks == 1 else "ended")

    def results(self, batch_id):
        reqs = self.created[int(batch_id.split("_")[1]) - 1]
        for k, r in enumerate(reqs):
            if k == len(reqs) - 1:                         # one request fails and is retried later
                yield types.SimpleNamespace(custom_id=r["custom_id"], result=types.SimpleNamespace(type="errored"))
                continue
            msg = types.SimpleNamespace(
                stop_reason="end_turn", model=r["params"]["model"],
                usage=types.SimpleNamespace(input_tokens=0, output_tokens=100_000),
                content=[types.SimpleNamespace(type="text", text=_fit(self.scores[k]).model_dump_json())])
            yield types.SimpleNamespace(custom_id=r["custom_id"], result=types.SimpleNamespace(type="succeeded", message=msg))


@pytest.fixture
def setup(tmp_path, profile, cv, settings):
    pytest.importorskip("anthropic")
    from jobstream.llm import LLM
    db = DB(tmp_path / "b.db")
    for i in range(4):
        db.upsert_job(Job(source="t", source_id=str(i), company=f"Acme {i}", title="IT Support Analyst",
                          description="Support 300 users. " * 100), "Acme Ltd")
    db.conn.execute("UPDATE jobs SET status='shortlisted', score=80")
    db.commit()
    batches = FakeBatches([82, 74, 40])
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=batches))
    llm = LLM("claude-opus-5-5", ledger=Ledger(tmp_path / "s.db"), client=client)
    return db, Context(profile, cv, settings), llm, batches


def test_batch_assessments_at_half_price(setup):
    db, ctx, llm, batches = setup
    say = []
    assert pipeline.assess_top(db, ctx, llm, say=say.append, batch=True) == 4
    req = batches.created[0][0]
    assert req["params"]["model"] == "claude-sonnet-5-5"               # assessments on Sonnet
    assert req["params"]["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in req["params"]                             # not allowed in batches
    assert pipeline.assess_top(db, ctx, llm, say=say.append, batch=True) == 0   # jobs in a batch aren't sent twice
    assert pipeline.harvest_batches(db, ctx, llm, say.append) == 0     # still running
    assert pipeline.harvest_batches(db, ctx, llm, say.append) == 3
    fits = {r["uid"]: r["fit_score"] for r in db.jobs()}
    assert sorted(v for v in fits.values() if v) == [40, 74, 82]
    assert json.loads(db.get_job("t:0")["assessment_json"])["rules"] >= 2
    assert pipeline._pending_batches(db) == []
    # Sonnet output at $10/M, halved: 3 x 100k tokens = $1.50
    assert llm.spent == pytest.approx(1.5)
    assert any("tried again" in m for m in say)
    # the failed one is picked up by the next batch
    assert pipeline.assess_top(db, ctx, llm, say=say.append, batch=True) == 1


def test_quick_check_applies_when_results_arrive(setup, monkeypatch):
    db, ctx, llm, _ = setup
    pipeline.assess_top(db, ctx, llm, say=lambda *_: None, batch=True)
    db.set_learned("daily_mode", "pack")
    done = []
    import jobstream.apply as apply_mod
    monkeypatch.setattr(apply_mod, "prepare_and_apply",
                        lambda db, ctx, llm, uid, mode=None, force=False: done.append((uid, mode)) or
                        types.SimpleNamespace(submitted=False, messages=[]))
    monkeypatch.setattr(pipeline, "load_register", lambda ctx: None)
    monkeypatch.setattr(pipeline, "collect", lambda *a, **k: pipeline.RunStats())
    monkeypatch.setattr(pipeline, "score_all", lambda *a, **k: 0)
    pipeline.harvest_batches(db, ctx, llm, lambda *_: None)            # first check: still running
    pipeline.watch(db, ctx, llm, say=lambda *_: None)
    assert [m for _, m in done] == ["pack", "pack"]                    # the two that reached 70
    assert pipeline.prepared_today(db) == 2


def test_networking_only_on_demand(tmp_path, monkeypatch, profile, cv, settings):
    import jobstream.apply as apply_mod
    from jobstream import networking
    monkeypatch.setattr(apply_mod, "OUTPUT_DIR", tmp_path / "out")
    calls = []
    real = networking.build_plan
    monkeypatch.setattr(networking, "build_plan", lambda *a, **k: calls.append(1) or real(*a, **k))
    db = DB(tmp_path / "n.db")
    db.upsert_job(Job(source="t", source_id="1", company="Acme", title="IT Support Analyst", description="Microsoft 365"),
                  "Acme Ltd")
    ctx = Context(profile, cv, settings)
    out = apply_mod.prepare_and_apply(db, ctx, None, "t:1", mode="pack")
    assert not calls and not (out.pack.dir / "networking.md").exists()
    md, path = apply_mod.build_networking(db, ctx, None, "t:1")       # on request: saved into the pack
    assert calls and path == out.pack.dir / "networking.md" and path.read_text(encoding="utf-8") == md
    assert json.loads(db.get_job("t:1")["extra"])["networking_at"]
