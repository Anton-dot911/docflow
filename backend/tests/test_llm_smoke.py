"""Real-API smoke test for app/llm, excluded from default runs (see pyproject).

Run manually with a real key: uv run --env-file .env pytest -m llm
"""

import os

import pytest
from pydantic import BaseModel

from app.llm import create_llm

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif("ANTHROPIC_API_KEY" not in os.environ, reason="needs ANTHROPIC_API_KEY"),
]


class Echo(BaseModel):
    message: str


def test_structured_echoes_through_the_real_api() -> None:
    llm = create_llm(project="docflow-backend", component="smoke-test")
    result = llm.structured(
        prompt_file="prompts/echo.v1.md",
        output_model=Echo,
        input={"message": "ping"},
    )
    assert isinstance(result, Echo)
    assert "ping" in result.message
