from fastapi.testclient import TestClient

from app.main import app
from app.version import get_commit_sha

client = TestClient(app)


def test_health_returns_ok_with_commit() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["commit"] == get_commit_sha()
    assert body["commit"]
