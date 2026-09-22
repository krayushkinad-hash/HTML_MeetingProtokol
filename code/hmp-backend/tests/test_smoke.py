"""Smoke tests for FastAPI app."""
from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    """Health endpoint should return 200 and status='ok'."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_openapi_docs_available_in_debug(client: TestClient) -> None:
    """OpenAPI docs should be served at /docs when DEBUG=true."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_protected_endpoint_requires_protocol_id(client: TestClient) -> None:
    """POST /protocols without file should return 422."""
    response = client.post("/api/v1/hmp/protocols")
    assert response.status_code == 422


def test_correlation_id_propagated(client: TestClient) -> None:
    """X-Correlation-Id should be passed through."""
    correlation_id = "test-correlation-12345"
    response = client.get(
        "/health",
        headers={"X-Correlation-Id": correlation_id},
    )
    assert response.headers.get("X-Correlation-Id") == correlation_id


def test_correlation_id_auto_generated(client: TestClient) -> None:
    """If no X-Correlation-Id, server should generate one."""
    response = client.get("/health")
    assert "X-Correlation-Id" in response.headers
    assert len(response.headers["X-Correlation-Id"]) > 0
