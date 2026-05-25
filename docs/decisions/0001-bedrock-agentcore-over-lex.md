# ADR-0001: Bedrock AgentCore (not Amazon Lex, not Connect Health) as the voice-agent runtime

**Status:** **Superseded by ADR-0011** (Session 0007, 2026-05-23). The
Connect-native AI agent + AgentCore Gateway pattern obviates the
AgentCore-runtime-versus-Lex framing entirely — Connect owns the
runtime; we own tools, not an agent loop. Kept on record for the
historical reasoning. **Do not implement against this ADR.**

**Original status:** Accepted
**Original date:** 2026-05-22

## Context

We need an AI voice agent that answers inbound calls, asks the caller for identifying information, calls Practice Fusion's FHIR endpoint to verify identity, and routes the call. Three candidate AWS runtimes:

1. **Amazon Connect Health** — pre-built Patient Verification agent. Per public AWS docs ([Patient Verification agent](https://docs.aws.amazon.com/connecthealth/latest/userguide/patient-verification-agent.html)), it queries **Epic FHIR APIs** specifically, and the [`FHIRServer` data type](https://docs.aws.amazon.com/connecthealth/latest/APIReference/API_FHIRServer.html) is documented only inside Patient Insights (`StartPatientInsightsJob`) — *not* inside `CreateDomain` or any patient-engagement configuration. There is no public knob to point Patient Verification at a non-Epic FHIR server. The non-Epic path goes through an undocumented "AWS Connect Health EHR proxy service" or AWS-selected data partners ([Connect Health FAQ](https://aws.amazon.com/health/connect-health/faqs/)).
2. **Amazon Lex bot + Bedrock Agents bridge** — older AWS reference pattern (the AWS sample [`sample-amazon-connect-bedrock-agent-voice-integration`](https://github.com/aws-samples/sample-amazon-connect-bedrock-agent-voice-integration) uses it). Lex handles ASR + NLU; bridges to a Bedrock Agent for fulfillment.
3. **Bedrock AgentCore Runtime** — AWS's newer managed agent runtime, supports bidirectional voice streaming, designed for LLM-driven dialog without an intermediate intent/slot model.

## Decision

Use **Bedrock AgentCore Runtime**, with the **Strands Agents SDK** for agent assembly and **Amazon Nova Sonic** (covered in ADR-0002) for the voice pipeline.

## Why

- **Connect Health is Epic-only at the public-API level.** We are Practice Fusion. Building around an undocumented partner path is not acceptable for a v1 we want to ship in months, not quarters.
- **Lex's intent/slot model is the wrong shape for verification.** Verification dialog branches based on what the FHIR lookup returned (match, multiple match, no match, ambiguous match) — those are not "intents" in the Lex sense. LLM-driven dialog handles this natively.
- **AgentCore supports bidirectional voice streaming.** Lex's voice support is request/response per utterance; AgentCore + Nova Sonic supports natural turn-taking with interruption handling.
- **User direction.** The user explicitly rejected Lex.

## Consequences

**Positive:**
- Single runtime owns NLU + dialog + tool-use. Fewer moving parts.
- Latency wins from bidirectional streaming.
- Prompt + tool changes are deploys of code, not bot-version-and-alias dances.

**Negative / costs:**
- AgentCore is newer; less community tooling than Lex.
- Voice quality depends on Nova Sonic — see ADR-0002 for the fallback plan.
- Cost is variable (Bedrock token + Nova Sonic stream pricing) vs. Lex's per-request pricing. Measure in Session 9.

## Alternatives considered

- **Build directly on Bedrock InvokeModel + custom streaming code.** Rejected: AgentCore handles the streaming + tool-call plumbing for us; rolling our own is reinventing the wheel.
- **Twilio Voice Agents + Bedrock.** Rejected: Connect is HIPAA-eligible under the AWS BAA and stays in-account; bringing Twilio in adds a second BAA to manage.
