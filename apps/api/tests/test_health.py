from fastapi.testclient import TestClient

from canonguard.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "CanonGuard"
    assert body["status"] in {"ok", "degraded"}
    assert "database" in body
