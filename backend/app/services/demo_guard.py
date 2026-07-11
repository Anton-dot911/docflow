"""FastAPI-facing demo guardrails (T9).

Thin glue between the pure `services/rate_limit.py` limiter and the routes
that need it: per-IP rate limiting, applied only to `/api/demo/*` endpoints
and to requests that touch one of the 5 fixed demo documents (see
`app/demo_data.py`) — never to normal (non-demo) traffic.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request, status

from app.demo_data import is_demo_document_id
from app.services.rate_limit import RateLimitExceeded, check_rate_limit

_TOO_MANY_REQUESTS_MESSAGE = "забагато запитів — спробуйте, будь ласка, за хвилину"


def enforce_demo_document_rate_limit(request: Request, document_id: UUID) -> None:
    """No-op for non-demo documents; per-IP rate limit for demo ones."""
    if not is_demo_document_id(document_id):
        return
    _check(request, "doc")


def enforce_demo_namespace_rate_limit(request: Request) -> None:
    """Rate limit for `/api/demo/*` endpoints not scoped to one document id."""
    _check(request, "demo")


def _check(request: Request, bucket: str) -> None:
    client_ip = request.client.host if request.client else "unknown"
    try:
        check_rate_limit(f"{bucket}:{client_ip}")
    except RateLimitExceeded as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY_REQUESTS_MESSAGE
        ) from error
