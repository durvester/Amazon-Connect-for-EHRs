"""Placeholder smoke test for the local-invoke shim (Session 0005)."""

from agent.local_invoke import invoke_synthetic


def test_invoke_synthetic_returns_ok() -> None:
    assert invoke_synthetic() == "ok"
