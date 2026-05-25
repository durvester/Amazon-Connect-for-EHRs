"""Smoke test for the agent loop. Real coverage arrives in Session 0005."""

import pytest


def test_import_works():
    """Sanity: the agent module imports cleanly."""
    import agent  # noqa: F401


def test_build_agent_not_implemented():
    """Marks the implementation gap for Session 0005."""
    from agent.agent import build_agent

    with pytest.raises(NotImplementedError):
        build_agent()
