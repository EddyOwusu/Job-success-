import shutil
import types
from pathlib import Path

import pytest
from pydantic import BaseModel

from jobstream.spend import Ledger, cost

ROOT = Path(__file__).resolve().parent.parent


def usage(i=0, o=0, cw=0, cr=0, searches=0):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_creation_input_tokens=cw,
                                 cache_read_input_tokens=cr,
                                 server_tool_use=types.SimpleNamespace(web_search_requests=searches))


def test_cost_from_list_prices():
    assert cost("claude-opus-5-5", usage(i=1_000_000)) == pytest.approx(4.0)
    assert cost("claude-opus-5-5", usage(o=1_000_000)) == pytest.approx(20.0)
    assert cost("claude-sonnet-5-5", usage(i=1_000_000, o=1_000_000)) == pytest.approx(12.0)
    assert cost("claude-opus-5-5", usage(cw=1_000_000, cr=1_000_000)) == pytest.approx(5.0 + 0.2)
    assert cost("claude-opus-5-5", usage(searches=3)) == pytest.approx(0.03)
    # your real run: 25 assessments on Opus, 54,523 in / 53,706 out
    assert cost("claude-opus-5-5", usage(i=54_523, o=53_706)) == pytest.approx(1.29, abs=0.01)


class Answer(BaseModel):
    ok: bool


class FakeClient:
    """Stands in for anthropic.Anthropic: each call costs $0.40 on Opus (20k output tokens)."""
    def __init__(self):
        self.models = []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(parse=self.parse))

    def parse(self, **kw):
        self.models.append(kw["model"])
        return types.SimpleNamespace(usage=usage(o=20_000), model=kw["model"], stop_reason="end_turn",
                                     parsed_output=Answer(ok=True))


def test_daily_budget_stops_claude(tmp_path):
    pytest.importorskip("anthropic")
    from jobstream.llm import LLM, BudgetReached, LLMError

    client = FakeClient()
    llm = LLM("claude-opus-5-5", budget_usd=1.0, ledger=Ledger(tmp_path / "s.db"), client=client)
    for _ in range(3):                                       # $0.40 each: 0.4, 0.8, 1.2
        llm.structured(system="s", prompt="p", schema=Answer)
    assert llm.over_budget() and llm.spent_today() == pytest.approx(1.2)
    with pytest.raises(BudgetReached):
        llm.structured(system="s", prompt="p", schema=Answer)
    assert issubclass(BudgetReached, LLMError)               # callers' no-Claude fallbacks still catch it
    # another process (the dashboard) sees the same day's spend
    other = LLM("claude-opus-5-5", budget_usd=1.0, ledger=Ledger(tmp_path / "s.db"), client=client)
    assert other.over_budget()
    # per-call model override (assessments on Sonnet)
    cheap = LLM("claude-opus-5-5", ledger=Ledger(tmp_path / "t.db"), client=client)
    cheap.structured(system="s", prompt="p", schema=Answer, model="claude-sonnet-5-5")
    assert client.models[-1] == "claude-sonnet-5-5" and cheap.spent == pytest.approx(0.2)


def test_budget_command_saves_settings(tmp_path, monkeypatch, capsys):
    from jobstream import cli, config
    for name in ("profile.example.yaml", "cv_master.example.yaml"):
        shutil.copy(ROOT / "config" / name, tmp_path / name)
    (tmp_path / "settings.yaml").write_text("apply:\n  max_applications_per_day: 10\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    cli.main(["budget", "--daily", "3", "--applications", "3", "--assess-model", "sonnet"])
    out = capsys.readouterr().out
    assert "Claude today:        $0.00 of $3.00" in out and "Applications a day:  3" in out
    s = config.load_context().settings
    assert s["llm"]["daily_budget_usd"] == 3.0 and s["apply"]["max_applications_per_day"] == 3
    assert s["llm"]["assess_model"] == "claude-sonnet-5-5" and s["llm"]["model"] == "claude-opus-5-5"
