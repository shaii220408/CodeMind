from fastapi.testclient import TestClient

from app.main import app


def test_allowlisted_local_frontend_private_network_preflight():
    with TestClient(app) as client:
        response = client.options(
            "/api/projects/sample/upload",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
                "Access-Control-Request-Private-Network": "true",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-private-network"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"]


def test_private_network_preflight_rejects_unlisted_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/projects/sample/upload",
            headers={
                "Origin": "https://unlisted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Private-Network": "true",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
