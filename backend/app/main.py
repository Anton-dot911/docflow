from fastapi import FastAPI
from pydantic import BaseModel

from app.version import get_commit_sha

app = FastAPI(title="docflow-backend")


class HealthResponse(BaseModel):
    status: str
    commit: str


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", commit=get_commit_sha())
