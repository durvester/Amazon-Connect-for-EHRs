"""Agent configuration. Real values arrive in Session 0005."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    model_id: str = "anthropic.claude-sonnet-4-6"
    region: str = "us-east-1"
    max_verification_attempts: int = 3
