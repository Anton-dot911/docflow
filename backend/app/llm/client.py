"""Metered Anthropic client wrapper with structured (tool-use) outputs.

Mirror of the TS contract in the antlab shared conventions: create_llm(project,
component) returns an Llm whose structured() forces a tool call shaped by a
Pydantic model, validates the result, and retries once with error feedback.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import MessageParam, ToolParam, ToolUseBlock
from meter import metered_client
from pydantic import BaseModel, ValidationError

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

    def structured(
        self,
        *,
        prompt_file: str,
        output_model: type[BaseModel],
        input: Any,
        model: str | None = None,
        temperature: float = 0,
    ) -> BaseModel:
        resolved_model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        system_prompt = (PROJECT_ROOT / prompt_file).read_text(encoding="utf-8")
        user_content = input if isinstance(input, str) else json.dumps(input, default=str)

        tool: ToolParam = {
            "name": TOOL_NAME,
            "description": "Report the result in the required structure.",
            "input_schema": output_model.model_json_schema(),
        }
        messages: list[MessageParam] = [{"role": "user", "content": user_content}]

        last_error: Exception | None = None
        for _ in range(2):  # first attempt + one retry with error feedback
            response = self._call_with_backoff(
                resolved_model, temperature, system_prompt, messages, tool
            )
            block = next((b for b in response.content if isinstance(b, ToolUseBlock)), None)
            if block is None:
                raise LlmError(
                    f"model returned no {TOOL_NAME} tool call (stop_reason={response.stop_reason})"
                )
            try:
                return output_model.model_validate(block.input)
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


def create_llm(project: str, component: str) -> Llm:
    return Llm(project=project, component=component)
