# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## How to start a session (cold pickup)

1. List `docs/sessions/` and open the **highest-numbered** file. Read its **"Next session pickup"** block first — that block is the authoritative starting point for the current session.
2. Skim `docs/context.md` (business background, decisions made) and `docs/architecture.md` (current target architecture).
3. If you're touching an area you don't recognize, check `docs/decisions/` (ADRs) for the rationale behind the existing design.
4. **If the session — or any prior pickup it references — names a new AWS service, API, CFN resource, or contact-flow / Lex / Bedrock block type that hasn't already been validated in this repo, *stop and verify it from primary-source AWS docs before any plan, ADR, or CDK code.*** Announcement copy and re:Invent posts are not sufficient. Required check: open the relevant API Reference / CFN resource list / flow-language actions reference and confirm (a) the exact Type/Action/Resource name, (b) the parameter shape, (c) the service namespace (e.g. `qconnect` vs `connect`, `AWS::Wisdom::*` vs `AWS::Connect::*`). Sessions 0007–0010 compounded three layers of architectural error because this step was skipped. See `memory/feedback_research_before_commitment.md`.
5. **Before architecture changes, the design must work back from quantifiable practice JTBDs**, not forward from AWS service capabilities. Each proposed primitive must answer "which JTBD does this serve, and what business metric does it move?" in one sentence, or it's not ready. See `memory/feedback_jtbd_drives_architecture.md`.
6. Before any architectural change, write a new ADR (`docs/decisions/NNNN-<slug>.md`). Don't quietly drift from the documented design. ADRs proposing pivots must satisfy step 4 (primary-source verification) and step 5 (JTBD anchor).

## Conventions (non-obvious)

- **TDD always.** Write the failing test first, then implement. Tests live next to code (`<package>/tests/`).
- **No PHI in logs, ever.** Log `practice_id`, `call_id`, decisions taken — never patient data values. Audit-log PHI disclosures to the dedicated S3 bucket (see `docs/architecture.md`).
- **Secrets via Secrets Manager only.** No secrets in env vars at rest, no secrets committed. The `.env.example` files show the shape of env vars but never contain real values.
- **IaC for everything.** Anything created via the AWS console is a bug. The CDK app in `infra/` is the source of truth.
- **HIPAA-eligible services only.** Don't introduce a new AWS service without confirming it's HIPAA-eligible and adding it to the architecture doc.
- **Session log at the end of every session.** The last action of any session is to write `docs/sessions/NNNN-<name>.md` using `docs/sessions/SESSION_TEMPLATE.md`. The "Next session pickup" block is the most important part — write it as concrete commands or file paths.

## What this repo is

AWS-native voice agent for patient verification + three other resolve-the-call FHIR use cases (lab/imaging status, visit summary, document/referral status), on inbound calls, integrated with Practice Fusion's FHIR R4 endpoint via SMART-on-FHIR OAuth (Provider App, user scopes). One pilot practice, then scale to 20K.

**Architecture (ADR-0018 + ADR-0019 + ADR-0020):**

```
DID → Connect contact flow
       → InvokeLambdaFunction (router) → phone_routing by DID → returns pf_org_uuid
       → If UNKNOWN → message + disconnect
       → UpdateContactAttributes → sets pf_org_uuid
       → ConnectParticipantWithLexBot (Lex bot; Nova 2 Sonic at locale level)
            → FallbackIntent → code-hook Lambda (every turn)
            → Code-hook calls Claude (Bedrock InvokeModel) with verification prompt
            → Claude reasons, requests tool calls → code-hook executes lookup_patient etc.
            → Code-hook returns Claude's response → Nova Sonic speaks it → loop
       → Close → contact flow routes to queue or disconnects
```

Each practice gets a dedicated DID; the router Lambda maps DID → `pf_org_uuid` via the `phone_routing` table (ADR-0014, ADR-0020). Per-practice FHIR base URL + OAuth tokens are looked up by `pf_org_uuid`. The code-hook Lambda is an LLM-powered agent: Claude receives the verification prompt (`agent/prompts/verification.md`) and conversation history every turn, decides what to say and when to call tools (ADR-0019). Lex + Nova 2 Sonic handle speech I/O only.

## What this repo is NOT (in v1)

- Not Amazon Connect Health prebuilt agents (PF is not a named partner). We integrate with Connect ourselves.
- Not an IVR / phone tree. The code-hook Lambda calls Claude every turn for natural conversation (ADR-0019). If it sounds like "press 1 for...", something is broken.
- Not AMAZON.BedrockAgentIntent (undocumented with Nova Sonic; see ADR-0019 evaluation).
- Not the (non-existent) "Connect native AI agent" with `InvokeAIAgent` block (ADR-0011 assumed it; ADR-0018 corrected it).
- Not Amazon Q in Connect text-AI agents (`qconnect:CreateAIAgent` / `AWS::Wisdom::AIAgent`).
- Not a custom AgentCore Runtime / Strands agent loop.
- `pf_org_uuid` is the practice key everywhere (ADR-0020). No invented `practice_id`.
- No appointment management, refills, clinical Q&A, or EHR write-back in v1.
