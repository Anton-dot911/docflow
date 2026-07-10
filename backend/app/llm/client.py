"""Metered Anthropic client wrapper with structured (tool-use) outputs.

create_llm(project, component) returns an Llm whose call_structured() loads a
prompt file, forces a tool call shaped by a Pydantic model, validates the
result with that same model, and retries once with the validation error fed
back to the model. Every request goes through the Meter wrapper so cost and
latency land in the shared Supabase ``llm_calls`` table.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from anthropic.types import MessageParam, ToolParam, ToolUseBlock
from meter import compute_cost, metered_client
from pydantic import BaseModel, ValidationError

# Output models are supplied by callers; the TypeVar keeps call_structured's
# return type tied to the passed output_model instead of collapsing to BaseModel.
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

# Fallback chain mirrors the TS contract: explicit arg > LLM_MODEL env > default.
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 60.0
# Sleep-then-retry on 429 (rate limited) / 529 (overloaded); other errors raise.
BACKOFF_SECONDS = (1.0, 4.0)
TOOL_NAME = "structured_output"

# prompt_file paths ("prompts/<name>.v<N>.md") resolve against the project
# root, which is two levels up from app/llm/.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LlmError(Exception):
    """The model did not produce output matching the schema."""


@dataclass(frozen=True)
class CallMetrics:
    """Cost/latency/usage for one structured call — persisted by callers (T5).

    Token counts and cost are summed across the initial attempt and the retry
    (when one runs); `latency_ms` is the wall time of the whole invocation.
    `model` is the id the API resolved the call to. `tokens_in`/`tokens_out`/
    `cost_usd` are None when the SDK reported no usage (e.g. under the unit-test
    mock) or the model is absent from the meter price table. `cost_usd` is a
    `Decimal` (CLAUDE.md rule 7), mirroring the meter's 5-decimal cost.
    """

    model: str
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: Decimal | None
    latency_ms: int


class Llm:
    def __init__(self, project: str, component: str) -> None:
        # SDK-internal retries are disabled so the explicit backoff below is
        # the single retry mechanism. Reads ANTHROPIC_API_KEY from the env.
        # metered_client wraps the SDK so every messages.create is recorded to
        # Meter (Supabase llm_calls) with cost/latency/tokens; it only observes
        # and never alters the response. The wrapper's return type is dynamic,
        # so annotate as the SDK client to keep static typing precise.
        self._client: anthropic.Anthropic = metered_client(
            anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0),
            project=project,
            component=component,
        )

    def call_structured(
        self,
        model: str | None,
        prompt_file: str,
        input: Any,
        output_model: type[OutputModelT],
        *,
        temperature: float = 0.0,
    ) -> OutputModelT:
        """Run one structured (tool-use) call and return a validated output_model.

        model: explicit model id, or None to resolve from LLM_MODEL / the default.
        prompt_file: "prompts/<name>.v<N>.md", read as the system prompt.
        input: str used verbatim, a list treated as ready-made content blocks
        (e.g. vision text+image blocks), else JSON-encoded as the user message.
        output_model: Pydantic model shaping the tool schema and validating the
        response; on validation failure exactly one retry runs with the error
        appended. Raises FileNotFoundError if the prompt file is missing (before
        any API call) and LlmError if the output is still invalid after the retry.
        """
        result, _metrics = self.call_structured_metered(
            model, prompt_file, input, output_model, temperature=temperature
        )
        return result

    def call_structured_metered(
        self,
        model: str | None,
        prompt_file: str,
        input: Any,
        output_model: type[OutputModelT],
        *,
        temperature: float = 0.0,
    ) -> tuple[OutputModelT, CallMetrics]:
        """As `call_structured`, but also return `CallMetrics` for persistence.

        Identical request/validate/retry behaviour; the extra return value
        carries the model id plus token/cost/latency summed over the attempt(s)
        so callers (T5 extraction) can write them to the `extractions` row. The
        meter wrapper still records each attempt independently to `llm_calls`.
        """
        resolved_model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        prompt_path = PROJECT_ROOT / prompt_file
        if not prompt_path.is_file():
            raise FileNotFoundError(
                f"prompt file not found: {prompt_file} (looked under {PROJECT_ROOT})"
            )
        system_prompt = prompt_path.read_text(encoding="utf-8")
        user_content = _as_user_content(input)

        tool: ToolParam = {
            "name": TOOL_NAME,
            "description": "Report the result in the required structure.",
            "input_schema": output_model.model_json_schema(),
        }
        messages: list[MessageParam] = [{"role": "user", "content": user_content}]

        start = time.monotonic()
        tokens_in_total = 0
        tokens_out_total = 0
        cost_total = Decimal("0")
        usage_seen = False
        cost_seen = False
        response_model = resolved_model
        last_error: Exception | None = None
        for _ in range(2):  # first attempt + one retry with error feedback
            response = self._call_with_backoff(
                resolved_model, temperature, system_prompt, messages, tool
            )
            response_model = getattr(response, "model", None) or resolved_model
            tokens_in = _usage_tokens(response, "input_tokens")
            tokens_out = _usage_tokens(response, "output_tokens")
            if tokens_in is not None or tokens_out is not None:
                usage_seen = True
                tokens_in_total += tokens_in or 0
                tokens_out_total += tokens_out or 0
            cost = compute_cost(response_model, tokens_in, tokens_out)
            if cost is not None:
                cost_seen = True
                cost_total += Decimal(str(cost))

            block = next((b for b in response.content if isinstance(b, ToolUseBlock)), None)
            if block is None:
                raise LlmError(
                    f"model returned no {TOOL_NAME} tool call (stop_reason={response.stop_reason})"
                )
            try:
                validated = output_model.model_validate(block.input)
            except ValidationError as error:
                last_error = error
                messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": (
                                    "The output failed schema validation:\n"
                                    f"{error}\n"
                                    f"Call {TOOL_NAME} again with corrected values."
                                ),
                                "is_error": True,
                            }
                        ],
                    },
                ]
                continue

            metrics = CallMetrics(
                model=response_model,
                tokens_in=tokens_in_total if usage_seen else None,
                tokens_out=tokens_out_total if usage_seen else None,
                cost_usd=cost_total if cost_seen else None,
                latency_ms=max(0, round((time.monotonic() - start) * 1000)),
            )
            return validated, metrics
        raise LlmError("output failed schema validation after one retry") from last_error

    def _call_with_backoff(
        self,
        model: str,
        temperature: float,
        system_prompt: str,
        messages: list[MessageParam],
        tool: ToolParam,
    ) -> anthropic.types.Message:
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            try:
                # Recorded to Meter automatically by the metered_client wrapper.
                response = self._client.messages.create(
                    model=model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    temperature=temperature,
                    system=system_prompt,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                )
            except anthropic.APIStatusError as error:
                if error.status_code not in (429, 529) or attempt == len(BACKOFF_SECONDS):
                    raise
                time.sleep(BACKOFF_SECONDS[attempt])
                continue
            return response
        raise AssertionError("unreachable: backoff loop always returns or raises")


def _as_user_content(input: Any) -> str | list[Any]:
    """Shape the user message content from a caller's ``input``.

    A ``str`` is used verbatim; a ``list`` is passed through as ready-made
    content blocks (T5 vision sends a text block plus base64 image blocks);
    anything else is JSON-encoded (dict inputs, e.g. the smoke test).
    """
    if isinstance(input, str):
        return input
    if isinstance(input, list):
        return input
    return json.dumps(input, default=str)


def _usage_tokens(response: Any, key: str) -> int | None:
    """Read ``response.usage.<key>`` as an int, or None if unavailable."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    value = getattr(usage, key, None)
    return value if isinstance(value, int) else None


def create_llm(project: str, component: str) -> Llm:
    return Llm(project=project, component=component)
