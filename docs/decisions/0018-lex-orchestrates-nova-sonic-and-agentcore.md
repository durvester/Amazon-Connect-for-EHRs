# ADR-0018: Lex bot orchestrates the call; Nova Sonic is the bot's speech model; AgentCore Gateway is reached via Lex code hook

**Status:** Accepted (supersedes ADR-0001, ADR-0004, ADR-0010, ADR-0011, ADR-0017)

**Date:** 2026-05-24 (Session 0010 discovery)

**Related:** ADR-0009 (audit + rate-limit, unchanged), ADR-0012 (MCP via
Gateway — *partially* changed: Lex Lambda code hook is now the
consumer, not a Connect-native AI agent), ADR-0013 (decision logic in
prompt — preserved but the prompt now lives on the Lex bot, not on a
Connect AIAgent), ADR-0014 (per-practice DID + phone_routing,
unchanged), ADR-0015 (FastAPI onboarding API, unchanged), ADR-0016
(state cache + single PF app, unchanged).

## Context

Sessions 0007–0009 assumed a "Connect native AI agent" surface — a
new `connect:CreateAIAgent` admin API, an `InvokeAIAgent` contact-flow
block, and an `AWS::Connect::AIAgent` CFN resource — would carry the
voice-verification reasoning and consume MCP tools through AgentCore
Gateway. Session 0010 attempted to deploy this stack and surfaced
three primary-source contradictions:

1. **`connect:CreateAIAgent` does not exist.** The actual AI-agent
   admin API is `qconnect:CreateAIAgent` in
   `@aws-sdk/client-qconnect`. It manages **Amazon Q in Connect**
   text-AI configurations (Answer Recommendation, Self-Service text,
   Manual Search, Note Taking, Email Generative Answer) — not voice
   orchestration. The CFN resource is `AWS::Wisdom::AIAgent`.
2. **There is no `InvokeAIAgent` contact-flow action.** The
   [Connect Flow Language actions
   reference](https://docs.aws.amazon.com/connect/latest/APIReference/flow-language-actions.html)
   lists `InvokeLambdaFunction`, `InvokeFlowModule`, the contact
   actions (`UpdateContactAttributes`, etc.), but no
   `InvokeAIAgent`. There is a `Connect assistant` block that hands
   off to Q in Connect — also text-AI, not Nova Sonic voice.
3. **Nova Sonic in Connect is configured at the Lex bot locale
   level**, not as a standalone agent. Per the official
   [Configure Nova Sonic Speech-to-Speech](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html)
   doc, you set the bot's speech model to "Speech-to-Speech: Amazon
   Nova Sonic" in the Conversational AI Bot admin UI; the contact
   flow continues to use `GetCustomerInput` (with the Lex bot
   target) plus a `Set voice` block for a Nova-Sonic-compatible
   voice. Lex still orchestrates intents and slots.

Separately, Connect contact flows also have **no `InvokeAWSService`
action** — there is no native DDB-from-flow primitive. AWS calls
from a flow go through `InvokeLambdaFunction`.

## Decision

**The voice surface is Lex-orchestrated:**

```
DID
 → Connect contact flow
    1. InvokeLambdaFunction (router_lambda) → reads phone-routing DDB
       by $.SystemEndpoint.Address, returns practice_id; flow sets it
       on $.Attributes via the Lambda response convention.
    2. GetCustomerInput (Lex bot target, Nova-Sonic-enabled bot)
       — Lex runs the verification dialog, calls a Lambda code
       hook on slot fulfilment.
 → Lex bot (one bot per env; Nova Sonic at the locale)
    - Slot-collected: caller name, dob, (phone is the ANI from Connect).
    - Code-hook Lambda calls AgentCore Gateway (MCP) for
      lookup_patient + future tools.
 → AgentCore Gateway (unchanged from ADR-0012)
    - Routes MCP tool calls to lookup_patient (and future tools).
```

**Concretely, this changes:**

- **No Connect AI agent provisioning.** Drop the Session 0009 `AwsCustomResource` block entirely; superseded by Lex bot provisioning.
- **No InvokeAIAgent contact-flow action.** The Session 0007/0009 contact flow JSON is rewritten against `InvokeLambdaFunction` + `GetCustomerInput`.
- **Phone-routing requires a router Lambda.** New tool/Lambda `tools/router_lookup` (working name) that reads `phone_routing` and returns `{practice_id}` to the flow. ADR-0014 unchanged on the table schema; only the access pattern changes.
- **The verification prompt becomes a Lex code-hook system prompt.** `agent/src/agent/prompts/verification.md` remains the canonical text (ADR-0013), but it ships into the Lex code-hook Lambda environment, not into a Connect AI agent. Nova Sonic handles the speech; Lex's intent/slot collection drives turn-taking; the code-hook Lambda decides next-action and may invoke `lookup_patient` through the Gateway.
- **The "candidates" decision logic from ADR-0013 still lives in the prompt** (LLM in the code-hook Lambda interprets the candidate list and picks the next utterance). Audit defensibility plan from ADR-0013 unchanged in spirit; the audit harness now tags Lex session id + Connect contact id together.

## Why Lex (Path A), not KVS-streaming (Path B)

User decision at session 0010 close: Path A. Rationale:

- **Lower infra footprint.** Path B (KVS → ECS/Fargate consuming the audio stream → Nova Sonic SDK + AgentCore Gateway) requires running our own real-time process and the streaming plumbing. Path A reuses Connect's Lex integration as the entry point, with a Lambda code hook as the only custom compute.
- **Faster to first-call.** Connect + Lex + Lambda code hook is a well-trodden path; Nova Sonic on Lex is configured in the Connect admin UI per the official runbook.
- **Single point of orchestration.** Lex owns turn-taking, intent fulfilment, and slot validation; the code-hook Lambda only runs deterministic FHIR lookups and prompts. Sessions 0011+ revisit if Lex's slot/intent model is too rigid for the verification dialog — but it's the obviously cheaper bet to start.

## What this means for sessions 0007–0009 artifacts

- **ADR-0001 (Bedrock AgentCore over Lex):** already marked Superseded (Session 0007). ADR-0018 re-confirms: Lex is back, but with Nova Sonic on it — not bare Lex.
- **ADR-0011 (Connect-native pivot):** **Superseded.** The pivot's premise (a "Connect native AI agent" with `InvokeAIAgent` block) was a misread of November 2025 announcements.
- **ADR-0017 (AwsCustomResource for AI agent + PhysicalResourceId per prompt_version):** **Superseded.** No `connect:CreateAIAgent`. The corresponding code in `infra/lib/connect-stack.ts` is left disabled in-place with a TODO pointing to ADR-0018; Session 0011 deletes it during the rewrite.
- **ADR-0012 (MCP via Gateway):** **Mostly preserved.** Gateway is still the MCP catalog; the consumer changes from "Connect AI agent" to "Lex code-hook Lambda." Tool schemas + the `lookup_patient` Lambda are unchanged.
- **ADR-0013 (decision in prompt):** **Preserved.** Reasoning still lives in a prompt; the runtime carrying the prompt changes from a hypothetical Connect AI agent to a Lex code-hook Lambda. Eval harness plan (Session 0013) unchanged.
- **`agent/src/agent/prompts/verification.md`:** **Preserved as-is** (the wording is fine; the "lookup_patient invocation contract" stays the same since it's about the tool, not the runtime).
- **Foundational stacks already deployed** (audit, rate-limit, phone-routing, agent-gateway): **Preserved.** No change needed.
- **`infra/lib/connect-stack.ts`:** **Rewrite required (Session 0011).** New flow content with router-Lambda + GetCustomerInput + Lex bot; no Connect AI agent; new `lex-stack.ts` for the Lex bot itself + Nova Sonic configuration (likely via `aws-cdk-lib/aws-lex` L1).
- **`infra/lib/api-stack.ts` (onboarding API):** **Preserved.** OAuth flow is independent of the call-time architecture.

## Open questions for Session 0011

- Lex CFN coverage: `AWS::Lex::Bot`, `AWS::Lex::BotAlias`,
  `AWS::Lex::BotVersion` are GA. The Nova Sonic config field is the
  unknown — needs primary-source verification ([[feedback_research_before_commitment]])
  before any CDK code.
- Code-hook Lambda contract: Lex's Lambda input/output schema for
  intent fulfilment + dialog code-hook. Confirm against official
  reference before writing.
- Whether the "decision in prompt" can live entirely in a single
  Lex slot fulfilment hook, or if it needs multiple intents.

## Kill criterion

If Lex's slot/intent model is too rigid to handle the verification
dialog cleanly (specifically: the disambiguation step in
`agent/src/agent/prompts/verification.md`'s "two or more candidates"
branch), revisit Path B (KVS streaming) and write ADR-0019. We do
not switch architectures based on a single bad eval result; switch
on a structural inability to express the policy.
