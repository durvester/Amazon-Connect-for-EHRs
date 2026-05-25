"""Minimal local-invoke entry point for the CI agent-e2e layer.

Session 0005 placeholder. Replaced/extended by Session 0010 (Strands +
recorded Connect ContactEvent playback). Today this exists so the CI
agent-e2e layer has something real to call — the slot is wired even
though the agent itself isn't built yet.
"""

from __future__ import annotations


def invoke_synthetic() -> str:
    """Return ``"ok"`` to signal the harness ran a Python entry point.

    Session 0010 replaces this with a real Strands Agent invocation against
    a recorded Connect ``ContactEvent`` payload.
    """
    return "ok"
