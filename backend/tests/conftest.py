"""Shared pytest fixtures.

`mock_llm` stands in for the Anthropic SDK so unit tests of app/llm exercise
the real call_structured logic (prompt loading, tool schema, validate + retry,
backoff) without any network or Meter/Supabase writes. The Meter wrapper is
replaced with a passthrough and time.sleep is neutralised, so the only thing a
test controls is what messages.create returns.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
from anthropic.types import ToolUseBlock

from app.llm import client as llm_client


@dataclass
class MockLlm:
    """Controller yielded by the `mock_llm` fixture.

    `create` is the mock standing in for client.messages.create — set its
    `.return_value` or `.side_effect` to script responses (and exceptions).
    """

    create: MagicMock

    def make(self, component: str = "unit-test") -> llm_client.Llm:
        """Build an Llm whose SDK client is the mocked, non-metered stand-in."""
        return llm_client.Llm(project="docflow", component=component)

    def tool_use(self, payload: dict[str, Any], *, block_id: str = "toolu_test") -> Any:
        """A Message-shaped stand-in carrying a single structured_output tool call."""
        block = ToolUseBlock(type="tool_use", id=block_id, name=llm_client.TOOL_NAME, input=payload)
        return SimpleNamespace(content=[block], stop_reason="tool_use")

    def rate_limit_error(self) -> anthropic.RateLimitError:
        """A real 429 error, so the backoff-on-429 branch is exercised."""
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        return anthropic.RateLimitError("rate limited", response=response, body=None)


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockLlm]:
    create = MagicMock(name="messages.create")
    fake_client = MagicMock(name="anthropic.Anthropic")
    fake_client.messages.create = create

    # Passthrough Meter wrapper: no llm_calls writes from unit tests.
    monkeypatch.setattr(llm_client, "metered_client", lambda client, **_kwargs: client)
    # Return the fake client from anthropic.Anthropic(...) — no API key required.
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_kwargs: fake_client)
    # Keep the backoff path instant.
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    yield MockLlm(create=create)
