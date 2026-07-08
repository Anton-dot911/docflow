"""Unit tests for app/llm/client.call_structured (SDK mocked via mock_llm)."""

from __future__ import annotations

import pytest
from conftest import MockLlm
from pydantic import BaseModel

from app.llm.client import LlmError

# An existing prompt file (resolved against the backend root); its contents are
# irrelevant here since the SDK is mocked — only that it loads matters.
PROMPT = "prompts/echo.v1.md"


class Widget(BaseModel):
    name: str
    count: int


def test_happy_path_returns_parsed_output_model(mock_llm: MockLlm) -> None:
    mock_llm.create.return_value = mock_llm.tool_use({"name": "bolt", "count": 3})

    result = mock_llm.make().call_structured(None, PROMPT, {"q": "x"}, Widget)

    assert isinstance(result, Widget)
    assert result == Widget(name="bolt", count=3)
    assert mock_llm.create.call_count == 1


def test_invalid_then_valid_retries_with_error_feedback(mock_llm: MockLlm) -> None:
    mock_llm.create.side_effect = [
        mock_llm.tool_use({"name": "bolt"}),  # missing count -> validation fails
        mock_llm.tool_use({"name": "bolt", "count": 3}),  # retry succeeds
    ]

    result = mock_llm.make().call_structured(None, PROMPT, {"q": "x"}, Widget)

    assert result == Widget(name="bolt", count=3)
    assert mock_llm.create.call_count == 2

    # The retry request must carry the validation error back to the model.
    retry_messages = repr(mock_llm.create.call_args_list[1].kwargs["messages"])
    assert "failed schema validation" in retry_messages
    assert "count" in retry_messages


def test_retry_exhausted_raises_typed_error(mock_llm: MockLlm) -> None:
    mock_llm.create.side_effect = [
        mock_llm.tool_use({"name": "bolt"}),  # invalid
        mock_llm.tool_use({"name": "screw"}),  # still invalid after retry
    ]

    with pytest.raises(LlmError):
        mock_llm.make().call_structured(None, PROMPT, {"q": "x"}, Widget)

    assert mock_llm.create.call_count == 2


def test_rate_limit_then_success_exercises_backoff(mock_llm: MockLlm) -> None:
    mock_llm.create.side_effect = [
        mock_llm.rate_limit_error(),  # 429 -> backoff, then retry
        mock_llm.tool_use({"name": "bolt", "count": 3}),
    ]

    result = mock_llm.make().call_structured(None, PROMPT, {"q": "x"}, Widget)

    assert result == Widget(name="bolt", count=3)
    assert mock_llm.create.call_count == 2


def test_missing_prompt_file_errors_before_any_api_call(mock_llm: MockLlm) -> None:
    with pytest.raises(FileNotFoundError):
        mock_llm.make().call_structured(None, "prompts/does_not_exist.v9.md", {"q": "x"}, Widget)

    assert mock_llm.create.call_count == 0
