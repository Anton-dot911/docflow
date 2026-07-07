from fastapi import FastAPI
from pydantic import BaseModel

from app.routes.documents import router as documents_router
from app.version import get_commit_sha

app = FastAPI(title="docflow-backend")

app.include_router(documents_router)


class HealthResponse(BaseModel):
    status: str
    commit: str


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", commit=get_commit_sha())
