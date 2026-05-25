# ADR-0011: Pivot to Connect native AI agent + AgentCore Gateway + MCP tools

**Status:** Superseded by [ADR-0018](0018-lex-orchestrates-nova-sonic-and-agentcore.md) (Session 0010 discovery — the premise of a "Connect native AI agent" with a CreateAIAgent admin API and an InvokeAIAgent contact-flow block is not real as of 2026-05; Lex with Nova Sonic is the actual surface).

**Date:** 2026-05-23 (Session 0007)

**Supersedes:** ADR-0001 (Bedrock AgentCore over Lex), ADR-0004 (Python
Strands SDK), ADR-0010 (Connect/KVS/AgentCore wiring).

**Retains:** ADR-0002 (Nova Sonic over Transcribe+Polly) — Nova Sonic
is now native to Connect's AI agent, so the underlying decision holds;
only the *delivery mechanism* changed.

## Context

Session 0007 opened with a roadmap to wire Amazon Connect → KVS →
AgentCore Runtime (container-hosted) → Nova Sonic → Strands agent loop.
Mid-session, two findings forced a rethink:

1. **The roadmap's mental model was already a generation behind.**
   AgentCore Runtime takes container images, not Lambdas. Connect's
   contact-flow JSON schema has no native AgentCore action block. A
   custom Lambda bridge would be required to glue Connect into
   AgentCore — captured (and now superseded) in ADR-0010.

2. **At re:Invent November 2025 AWS launched native AI agents *inside*
   Amazon Connect**, powered by Nova Sonic for bidirectional speech
   and consuming tools via MCP through **Bedrock AgentCore Gateway**.
   These agents are first-party to Connect: they own audio, ASR/TTS,
   and the agent loop. The only thing the developer brings is tools
   (any Lambda exposed via OpenAPI through Gateway) and a system
   prompt.

In March 2026, AWS layered **Amazon Connect Health** on top — a
HIPAA-eligible product with five prebuilt healthcare AI agents
including a GA Patient Verification agent. Connect Health ships with
named EHR partners (Veradigm, Greenway, Netsmart, Redox, HealthLake).
**Practice Fusion is not on the partner list.** We therefore do not
adopt Connect Health's prebuilt verification agent; we ride on the
same **Connect-native AI agent + AgentCore Gateway** plumbing with our
own four FHIR tools.

## Decision

The voice wire from this point forward is:

```
Patient dials practice's dedicated DID
   → Amazon Connect (single shared instance)
   → Contact flow:
        1. Read $.SystemEndpoint.Address (the DID)
        2. Resolve practice_id via DDB GetItem on phone_routing table
           (Connect-native InvokeAWSService — no glue Lambda)
        3. Set practice_id as a contact attribute
        4. Hand off to native AI agent
   → Connect native AI agent (Nova Sonic; native ASR/TTS)
        — receives practice_id from the contact attribute and passes it
          into every tool call
   → AgentCore Gateway (MCP tool catalog; one Target per Lambda)
   → Lambdas (lookup_patient, lab_result_status, visit_summary,
              document_status)
        — each takes practice_id as input; looks up per-practice
          credentials from practices_store + token_store; rate-limits
          on (practice_id, ANI)
   → Practice Fusion FHIR R4
```

We **drop**:

- KVS bidirectional streaming (not needed — Connect native agent owns
  audio).
- Container-hosted AgentCore Runtime (not needed — Connect native
  agent owns reasoning).
- Strands SDK / custom agent loop (not needed — Connect native agent
  owns the loop; ADR-0004 superseded).
- The Connect → Lambda → AgentCore bridge contemplated in ADR-0010
  (no bridge; Connect's AI-agent action block calls Gateway directly).
- Amazon Lex (not part of the new wire; the older "Connect → Lex →
  Bedrock Agent" pattern is itself a generation behind).

We **retain** every piece of work from Sessions 0001–0006 unchanged:
`oauth/`, `audit/`, `tools/lookup_patient/` (modulo a slim refactor
per ADR-0013), `infra/lib/{audit,rate-limit}-stack.ts`,
`infra/config/envs.ts` (ADR-0008's env-context binding), and the
four-layer CI harness.

### GA / HIPAA gate (verified before this ADR landed)

All four feature services confirmed GA and HIPAA-eligible in
`us-east-1` at Session 0007 (2026-05-23):

| Service | GA | HIPAA | Region |
|---|---|---|---|
| Amazon Connect | Yes (long-standing) | Listed directly on HIPAA-eligible services reference | us-east-1 |
| Amazon Connect AI agents | Nov 2025 launch | Inherited via Connect parent | us-east-1 |
| Amazon Bedrock AgentCore | GA | Listed directly | us-east-1 |
| AgentCore Gateway | GA feature of AgentCore | Inherited via AgentCore parent | us-east-1 |
| Amazon Nova 2 Sonic | Dec 2025 launch | Bedrock HIPAA-eligible umbrella; AWS HIPAA-compliance-for-generative-AI guidance calls Nova out explicitly | us-east-1 |

The page note on the HIPAA-eligible-services reference applies:
*"generally available features of each of the HIPAA eligible services
listed are also considered HIPAA eligible."* This covers Connect AI
agents, Gateway, and Nova Sonic by inheritance. AWS BAA for account
`086514900943` confirmed in force by the user before this ADR landed.

**Caveat for compliance review.** AgentCore Gateway HIPAA eligibility
is by inheritance, not direct listing. Before pilot deploy (Session
0014), reconfirm with the AWS account team that the inherited
eligibility covers PHI flowing through Gateway tool invocations.

## Consequences

**Good**

- Operational weight drops dramatically. No container builds, no KVS
  retention tuning, no Strands version pinning, no Connect-flow JSON
  hand-craft for media streaming.
- One BAA, one IAM model, one cloud. No multi-vendor procurement.
- Extensibility surface (ADR-0012) collapses cleanly: four tools sit
  behind one MCP catalog, consumable by today's voice agent and any
  future MCP client (PF chat surface, internal staff tools, partner
  integrations).
- The architectural lane stays inside AWS-native, matching the
  trajectory of the existing ADRs.

**Less good**

- We accept several Plan-agent-flagged risks the user opted to handle
  in flight rather than spike up front:
  - "Connect AI agent → Gateway with no bridge" is unproven by AWS
    sample at the time of this ADR. Session 0009 is the empirical
    proof; if a bridge is needed, we add one and update this ADR.
  - AgentCore Gateway tool timeout is **30 s** per invocation. Our
    `lookup_patient` p99 against PF QA is plausibly 12–18 s with
    refresh + multiple probes; we monitor and split into "search" +
    "confirm" if the tail exceeds 20 s.
  - Verification decision logic is in the agent prompt (ADR-0013).
    LLM non-determinism in a regulated gate is a real audit risk; the
    audit plan in ADR-0013 mitigates it but does not eliminate it.
  - Per-practice OAuth context passes from the contact attribute
    `practice_id` (set in the contact flow) through MCP into the
    Lambda. If the native agent does not forward attributes
    faithfully, fall back to ANI lookup inside the Lambda.

**Kill criteria.** If by the end of Session 0009 we cannot demonstrate
end-to-end a real call producing a verified outcome with ADR-0006
compliance, revert to Pipecat-on-AgentCore-Runtime. Session 0007's
research output is sufficient to scope that pivot.

## Stale doc cleanup

CLAUDE.md's line "Not Amazon Connect Health (Epic-only)" is out of
date as of March 2026. Removed in this session. Replacement: "Not
Amazon Connect Health prebuilt agents (Practice Fusion is not a
named EHR partner)."

## Related

- ADR-0001 — superseded (BedrockAgentCore-over-Lex framing is moot
  when Connect owns the runtime).
- ADR-0002 — retained (Nova Sonic is the right model; delivery
  changed).
- ADR-0004 — superseded (no custom Strands agent loop).
- ADR-0006 — still binding (PF telecom literal-not-fuzzy rule must
  be enforced in the Lambda's FHIR client, not in the prompt).
- ADR-0008 — still binding (every new stack follows the env-context
  pattern).
- ADR-0010 — superseded (Connect/KVS/AgentCore wiring; replaced by
  this ADR and ADR-0012).
- ADR-0012 — companion (MCP-via-Gateway as the extensibility surface).
- ADR-0013 — companion (decision logic in prompt; audit plan).
- ADR-0014 — companion (per-practice DID + phone_routing).
