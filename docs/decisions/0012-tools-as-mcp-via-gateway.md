# ADR-0012: Tools-as-MCP-via-Gateway as the canonical extensibility surface

**Status:** Superseded by [ADR-0018](0018-lex-orchestrates-nova-sonic-and-agentcore.md) / [ADR-0019](0019-llm-powered-code-hook.md) — the code-hook Lambda imports tools directly; the AgentCore Gateway stack was removed in Session 0017.

**Date:** 2026-05-23 (Session 0007)

**Related:** ADR-0011 (the pivot itself), ADR-0008 (env-context CDK).

## Context

The product needs four FHIR-backed tools in v1 (verification + lab
status + visit summary + document/referral status) and is likely to
grow more over time. The voice agent is the *first* consumer; PF will
plausibly want at least two more consumers within a year (an in-app
patient chat surface, internal staff dashboards). Building per-consumer
tool integrations would 4×N our work.

Bedrock AgentCore Gateway is purpose-built for this: it converts a
Lambda + an OpenAPI 3.0 spec into an MCP tool with no hand-written MCP
plumbing. Any MCP client (Connect AI agent today, future PF chat,
LangGraph notebooks, etc.) consumes the same tool through the same
endpoint.

## Decision

**Every tool ships with three artifacts, co-located in
`tools/<tool>/`:**

1. **`src/<tool>/handler.py`** — the Lambda. Standard
   `event + context → JSON` signature; takes `practice_id` as a
   required input (per ADR-0014); writes one audit-disclosure record
   per FHIR probe; passes through the rate-limit gate before any
   network call; refreshes credentials on 401 once.
2. **`openapi.yaml`** — the OpenAPI 3.0 spec. This is the contract.
   Inputs and outputs match the handler's JSON shape exactly. The
   spec is checked into the repo, version-controlled, and
   round-tripped against the handler in a unit test.
3. **A `Target` entry in `infra/lib/agent-gateway-stack.ts`** —
   registers the Lambda + OpenAPI pair as a Gateway target,
   automatically converting to MCP at deploy time.

**Naming.** Each Gateway target is named `<tool>` (matching the
package directory). The MCP tool name surfaced to agents is also
`<tool>`. Agents discover tools through Gateway's semantic search.

**Authentication.** Gateway's ingress uses Cognito-based OAuth (per
the AgentCore healthcare reference architecture). Connect's AI agent
holds the Gateway OAuth client credential and exchanges it for a
short-lived access token per session. Egress (Gateway → Lambda) uses
IAM `lambda:InvokeFunction` granted to the Gateway execution role.

**No hand-written MCP.** We never author MCP server code. If Gateway
can't express a tool we want (e.g., streaming responses), we re-shape
the tool to fit Gateway's OpenAPI/MCP semantics rather than building
our own MCP server. If Gateway proves genuinely insufficient, a new
ADR documents the gap and the alternative.

**No "fat" tools.** Each Lambda does one verb against one FHIR
resource type. Don't bundle "verify patient + fetch labs" into one
tool just because they're called in sequence. Agents compose tools;
tools don't compose other tools.

**Tool timeouts.** Gateway enforces a 30 s per-invocation timeout
(documented). Each tool's p99 latency budget is therefore 25 s with
5 s headroom. If a tool exceeds that, split it into a "search" +
"confirm" two-call dance rather than ask for a Gateway exception.

## Consequences

**Good**

- Adding a new tool is one Lambda + one YAML + one CDK target — three
  artifacts in one directory.
- Same four tools serve any future MCP consumer without changes;
  no per-channel duplication.
- OpenAPI specs are versioned alongside the code that fulfills them;
  drift is a failed unit test, not a runtime surprise.

**Less good**

- 30 s timeout is real and binding. `lookup_patient` is at risk in the
  worst case (refresh + multiple probes); we monitor and split if
  needed.
- Gateway's MCP conversion is a managed-service black box; tool-shape
  changes ride on Gateway's behavior, which we don't control. If
  Gateway changes its conversion semantics, we adapt.
- Vendor lock-in to AgentCore Gateway. Mitigation: the tool contract
  (Lambda + OpenAPI) is portable — re-pointing the OpenAPI at any
  generic MCP gateway or building one in-house is a contained
  rewrite that doesn't touch the tools themselves.

## What this ADR does NOT decide

- *Which* tools we build. Roadmap owns that.
- The Lambda's internal structure (audit, rate-limit, refresh) —
  already settled in ADR-0009.
- Where the per-tenant `practice_id` comes from — ADR-0014.

## Related

- ADR-0011 — the pivot.
- ADR-0014 — per-practice DID + phone_routing.
- ADR-0009 — audit + rate-limit at the tool boundary.
- ADR-0006 — PF telecom literal-search rule (enforced inside the
  Lambda's FHIR client, not in the OpenAPI spec).
