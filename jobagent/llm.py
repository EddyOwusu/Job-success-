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


class LLM:
    """Structured calls to Claude. One instance per run."""

    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic  # imported lazily so the agent runs without the package

        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4)
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0

    def structured(self, *, system: str, prompt: str, schema: type[T], effort: str = "medium",
                   max_tokens: int = 16000, cache_system: bool = True) -> T:
        """Ask Claude for a JSON answer that validates against `schema`."""
        a = self.anthropic
        system_blocks = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}
        try:
            resp = self.client.beta.messages.parse(
                model=self.model,
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

        if resp.usage:
            self.input_tokens += resp.usage.input_tokens or 0
            self.output_tokens += resp.usage.output_tokens or 0
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
                if resp.usage:
                    self.input_tokens += resp.usage.input_tokens or 0
                    self.output_tokens += resp.usage.output_tokens or 0
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

    def usage_summary(self) -> str:
        return f"{self.input_tokens:,} input / {self.output_tokens:,} output tokens"


def make_llm(settings: dict) -> Optional[LLM]:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        return LLM(settings["llm"]["model"])
    except ImportError:
        log.warning("The `anthropic` package is not installed; running without Claude")
        return None
