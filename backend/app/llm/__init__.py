from app.llm.client import Llm, LlmError, create_llm

# Every DocFlow LLM call is metered under this Meter project (recorded to the
# shared Supabase `llm_calls` table). Use create_docflow_llm so the project is
# pinned in one place rather than passed at each call site.
PROJECT = "docflow"


def create_docflow_llm(component: str) -> Llm:
    """Create a metered LLM client bound to the DocFlow Meter project."""
    return create_llm(project=PROJECT, component=component)


__all__ = ["PROJECT", "Llm", "LlmError", "create_docflow_llm", "create_llm"]
