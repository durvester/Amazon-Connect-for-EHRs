"""Tests for the health-check route. Real coverage; this one's done."""

from api.routes.health import health


def test_health_returns_ok():
    assert health() == {"status": "ok"}
