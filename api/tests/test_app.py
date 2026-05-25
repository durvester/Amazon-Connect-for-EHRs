"""build_app smoke test: /healthz responds 200 with {'status': 'ok'}."""

from fastapi.testclient import TestClient

from api.app import build_app


def test_build_app_exposes_healthz() -> None:
    client = TestClient(build_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
