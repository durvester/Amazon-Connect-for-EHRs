"""Health check route."""

from __future__ import annotations


def health():
    """Tiny health response. The TDD seed exercises this."""
    return {"status": "ok"}
