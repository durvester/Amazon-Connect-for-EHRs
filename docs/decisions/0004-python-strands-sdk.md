# ADR-0004: Python + Strands Agents SDK for the agent

**Status:** **Superseded by ADR-0011** (Session 0007, 2026-05-23). The
Connect-native AI agent owns the agent loop in the pivoted
architecture — no Strands runtime is built or hosted by us. Tools
remain Python (Lambdas), but there is no Strands `Agent` object, no
in-process tool loop, and no agent-framework dependency.
**Do not implement against this ADR.**

**Original status:** Accepted
**Original date:** 2026-05-23

## Context

We need to pick a language and agent framework for the AgentCore-hosted voice agent. Constraints:

- AgentCore Runtime supports Python natively; other languages require wrapping.
- The agent has three tools — small, well-defined Lambda functions.
- We want to avoid heavy framework lock-in; the agent loop and tool registration should be straightforward.

Candidate frameworks: Strands Agents (AWS-native), LangGraph, CrewAI, hand-rolled on `bedrock-runtime` SDK.

## Decision

**Python 3.12 + Strands Agents SDK** for the agent. Tools are also Python Lambdas, packaged independently.

## Why

- **AWS-native.** Strands is built and maintained by AWS, ships with AgentCore samples, and gets first-class integration support.
- **Minimal boilerplate.** Tool registration via decorators; agent loop is one constructor call. No graph definitions to maintain.
- **Python everywhere.** Tools, agent, OAuth service, and API are all Python — one language across the backend lowers cognitive overhead.
- **First-class observability.** Strands integrates with the AWS X-Ray SDK and structured logging.

## Consequences

**Positive:**
- One Python toolchain (`pyproject.toml`, `ruff`, `pytest`) across all backend packages.
- Easy to swap LLMs (Claude Sonnet 4.6 ↔ Haiku 4.5) via Strands config.

**Negative:**
- Strands is younger than LangGraph; some advanced agent patterns (multi-agent, plan-execute) less battle-tested. Not a v1 concern.
- Lock-in to AWS-native abstractions. Acceptable trade-off given the rest of the stack is AWS-native anyway.

## Alternatives considered

- **LangGraph.** Strong framework but adds graph-modeling overhead not needed for a single-agent verification flow.
- **Hand-rolled on `bedrock-runtime`.** Would work but means writing the tool-use parsing loop ourselves. Strands does this well enough.
- **TypeScript/Node.** AgentCore Python ergonomics are better; mixing Node + Python in the backend would be more complexity than it removes.
