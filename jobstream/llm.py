"""Thin wrapper around the Claude API for structured (Pydantic) outputs."""
from __future__ import annotations

import logging
import os
from typing import Optional, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class BudgetReached(LLMError):
    """Today's Claude budget is spent: callers fall back to their no-Claude path."""


def json_schema(schema: type[BaseModel]) -> dict:
    """The JSON schema the API's structured outputs accept, for a Pydantic model."""
    try:
        from anthropic import transform_schema       # the SDK's own converter (newer SDKs)
        return transform_schema(schema)
    except ImportError:
        pass

    def strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for k in ("default", "title"):
                node.pop(k, None)
            for v in node.values():
                strict(v)
        elif isinstance(node, list):
            for v in node:
                strict(v)
        return node
    return strict(schema.model_json_schema())


class LLM:
    """Structured calls to Claude. One instance per run."""

    def __init__(self, model: str = "claude-opus-5-5", budget_usd: float = 0.0, ledger=None, client=None):
        import anthropic  # imported lazily so the agent runs without the package

        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic(max_retries=4)
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.spent = 0.0                 # this process
        self.budget_usd = budget_usd     # per day, all processes; 0 = no limit
        self.ledger = ledger

    # ------------------------------------------------------------------ budget
    def spent_today(self) -> float:
        return self.ledger.today() if self.ledger else self.spent

    def over_budget(self) -> bool:
        return bool(self.budget_usd) and self.spent_today() >= self.budget_usd

    def _check_budget(self) -> None:
        if self.over_budget():
            raise BudgetReached(f"Today's Claude budget (${self.budget_usd:.2f}) is used up; carrying on without Claude "
                                f"until tomorrow")

    def _charge(self, resp, model: str, task: str) -> None:
        from .spend import cost
        if not resp.usage:
            return
        self.input_tokens += resp.usage.input_tokens or 0
        self.output_tokens += resp.usage.output_tokens or 0
        usd = cost(getattr(resp, "model", None) or model, resp.usage)
        self.spent += usd
        if self.ledger:
            self.ledger.add(usd, model, task)

    def structured(self, *, system: str, prompt: str, schema: type[T], effort: str = "medium",
                   max_tokens: int = 16000, cache_system: bool = True, model: Optional[str] = None) -> T:
        """Ask Claude for a JSON answer that validates against `schema`. model: override for this call."""
        a = self.anthropic
        model = model or self.model
        self._check_budget()
        system_blocks = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}
        try:
            resp = self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=schema,
                # If a safety classifier declines, retry on a recommended fallback model.
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except a.AuthenticationError as e:
            raise LLMError("Claude API key is missing or invalid (set ANTHROPIC_API_KEY in .env)") from e
        except a.RateLimitError as e:
            raise LLMError(f"Claude rate limit reached: {e.message}") from e
        except a.BadRequestError as e:
            raise LLMError(f"Claude rejected the request: {e.message}") from e
        except a.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API (network problem)") from e

        self._charge(resp, model, schema.__name__)
        if resp.stop_reason == "refusal":
            raise LLMError(f"Claude declined this request: {getattr(resp.stop_details, 'explanation', '')}")
        if resp.stop_reason == "max_tokens":
            raise LLMError("Claude's answer was cut off (max_tokens). Try again or raise max_tokens.")
        parsed: Optional[T] = resp.parsed_output
        if parsed is None:
            raise LLMError("Claude returned no structured output")
        return parsed

    def research(self, prompt: str, *, max_searches: int = 8, effort: str = "medium",
                 max_continuations: int = 4) -> tuple[str, list[tuple[str, str]]]:
        """Free-text research with Claude's web search. Returns (notes, [(title, url)]).

        Only send what is needed to search (company, role, advert): never the candidate's details.
        Web search must be allowed for your organisation in the Claude Console.
        """
        a = self.anthropic
        self._check_budget()
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
                  "user_location": {"type": "approximate", "country": "GB"}}]
        messages = [{"role": "user", "content": prompt}]
        assistant_blocks: list = []
        text_parts: list[str] = []
        sources: dict[str, str] = {}
        try:
            for _ in range(max_continuations + 1):
                resp = self.client.beta.messages.create(
                    model=self.model, max_tokens=16000, messages=messages, tools=tools,
                    thinking={"type": "adaptive"}, output_config={"effort": effort},
                    betas=[FALLBACK_BETA], fallbacks="default",
                )
                self._charge(resp, self.model, "research")
                for block in resp.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                        for c in getattr(block, "citations", None) or []:
                            url = getattr(c, "url", None)
                            if url:
                                sources.setdefault(url, getattr(c, "title", None) or url)
                if resp.stop_reason == "pause_turn":   # the server's search loop paused: let it continue
                    assistant_blocks += list(resp.content)
                    messages = [{"role": "user", "content": prompt},
                                {"role": "assistant", "content": assistant_blocks}]
                    continue
                if resp.stop_reason == "refusal":
                    raise LLMError("Claude declined the research request")
                break
        except a.BadRequestError as e:
            raise LLMError(f"Web research failed ({e.message}). Is web search enabled for your organisation "
                           f"in the Claude Console?") from e
        except a.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API (network problem)") from e
        return "".join(text_parts).strip(), [(t, u) for u, t in sources.items()]

    # ------------------------------------------------------------------ batches (half price, results within hours)
    def batch_submit(self, items: list[tuple[str, str, str]], schema: type[BaseModel], effort: str = "medium",
                     model: Optional[str] = None, max_tokens: int = 16000) -> str:
        """Send many structured requests as one Message Batch. items: (custom_id, system, prompt).
        Returns the batch id. Batches can't use server-side fallbacks, so a declined request just fails
        and is tried again later."""
        a = self.anthropic
        model = model or self.model
        self._check_budget()
        fmt = {"type": "json_schema", "schema": json_schema(schema)}
        requests = [{"custom_id": cid, "params": {
            "model": model, "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort, "format": fmt},
        }} for cid, system, prompt in items]
        try:
            return self.client.messages.batches.create(requests=requests).id
        except a.APIStatusError as e:
            raise LLMError(f"Claude batch was rejected ({e.status_code}): {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API (network problem)") from e

    def batch_status(self, batch_id: str) -> str:
        """'in_progress', 'canceling' or 'ended'."""
        return self.client.messages.batches.retrieve(batch_id).processing_status

    def batch_results(self, batch_id: str, schema: type[T], model: Optional[str] = None
                      ) -> list[tuple[str, Optional[T], str]]:
        """[(custom_id, parsed or None, error)] for an ended batch. Charges the ledger at batch prices."""
        from .spend import cost
        model = model or self.model
        out: list[tuple[str, Optional[T], str]] = []
        for item in self.client.messages.batches.results(batch_id):
            res = item.result
            if res.type != "succeeded":
                out.append((item.custom_id, None, res.type))
                continue
            msg = res.message
            if msg.usage:
                self.input_tokens += msg.usage.input_tokens or 0
                self.output_tokens += msg.usage.output_tokens or 0
                usd = cost(getattr(msg, "model", None) or model, msg.usage) * 0.5     # batch discount
                self.spent += usd
                if self.ledger:
                    self.ledger.add(usd, model, schema.__name__ + " (batch)")
            if msg.stop_reason != "end_turn":
                out.append((item.custom_id, None, msg.stop_reason or "no answer"))
                continue
            text = next((b.text for b in msg.content if b.type == "text"), "")
            try:
                out.append((item.custom_id, schema.model_validate_json(text), ""))
            except ValueError as e:
                out.append((item.custom_id, None, f"unreadable answer: {e.__class__.__name__}"))
        return out

    def usage_summary(self) -> str:
        out = f"{self.input_tokens:,} input / {self.output_tokens:,} output tokens, about ${self.spent:.2f}"
        if self.ledger:
            out += f"; today ${self.spent_today():.2f}" + (f" of ${self.budget_usd:.2f}" if self.budget_usd else "")
        return out


def make_llm(settings: dict) -> Optional[LLM]:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        from .config import DATA_DIR
        from .spend import Ledger
        return LLM(settings["llm"]["model"], budget_usd=float(settings["llm"].get("daily_budget_usd") or 0),
                   ledger=Ledger(DATA_DIR / "spend.db"))
    except ImportError:
        log.warning("The `anthropic` package is not installed; running without Claude")
        return None
