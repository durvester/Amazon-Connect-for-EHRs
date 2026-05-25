# agent/

Bedrock AgentCore voice agent. Strands Agents SDK builds the agent; AgentCore Runtime hosts it; Nova Sonic provides the voice pipeline.

This package is the **agent assembly** — system prompt, model choice, tool registration. The tools themselves live in sibling packages under `../tools/`.

## Status

Scaffold only. Real assembly happens in Session 0005 (per `docs/sessions/0001-bootstrap.md`).
