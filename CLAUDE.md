# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## How to start a session (cold pickup)

1. Skim `docs/context.md` (business background, decisions made) and `docs/architecture.md` (current target architecture).
2. If you're touching an area you don't recognize, check `docs/decisions/` (ADRs) for the rationale behind the existing design.
3. **Before referencing a new AWS service, API, CFN resource, or contact-flow / Lex / Bedrock block type, verify it from primary-source AWS docs before any plan, ADR, or CDK code.** Announcement copy and re:Invent posts are not sufficient. Required check: open the relevant API Reference / CFN resource list / flow-language actions reference and confirm (a) the exact Type/Action/Resource name, (b) the parameter shape, (c) the service namespace (e.g. `qconnect` vs `connect`, `AWS::Wisdom::*` vs `AWS::Connect::*`).
4. **Before architecture changes, the design must work back from quantifiable practice JTBDs**, not forward from AWS service capabilities. Each proposed primitive must answer "which JTBD does this serve, and what business metric does it move?" in one sentence, or it's not ready.
5. Before any architectural change, write a new ADR (`docs/decisions/NNNN-<slug>.md`). Don't quietly drift from the documented design.

## Build, test, lint

Prerequisites: Python 3.12, Node 22, AWS CLI v2 (SSO to your AWS account, `us-east-1`), CDK v2.

```bash
make bootstrap          # one-time: venv + pip install all Python pkgs + npm install for infra/
make test               # all tests: pytest (every Python pkg) + jest (infra)
make lint               # ruff (Python) + tsc --noEmit (infra)
make synth              # cdk synth snapshot
```

Run a single Python package's tests (from repo root):
```bash
cd tools/lookup_patient && PYTHONPATH=src .venv/bin/python -m pytest -q
```

Run only unit tests (skip integration):
```bash
cd tools/lookup_patient && PYTHONPATH=src .venv/bin/python -m pytest -q -m "not integration"
```

Infra tests: `cd infra && npm test`

Python packages use `src/` layout with editable installs (`pip install -e .[dev]`). Tests require `PYTHONPATH=src` when running from a package directory. Ruff line-length is 100, target Python 3.12.

## Package map

All Python packages follow the same pattern: `<pkg>/src/<module>/`, `<pkg>/tests/`, `<pkg>/pyproject.toml`.

| Package | What it is |
|---|---|
| `tools/lex_code_hook/` | THE Lambda entry point: Lex calls this every turn, it invokes Claude via Bedrock and dispatches tool calls. Prompts live at `tools/lex_code_hook/src/lex_code_hook/prompts/` |
| `tools/lookup_patient/` | FHIR Patient search by phone/name/DOB |
| `tools/fhir_query/` | Generic FHIR query tool — Claude composes queries, code enforces allowlists + projections |
| `tools/router_lookup/` | DID → `pf_org_uuid` lookup from `phone_routing` DynamoDB table |
| `oauth/` | SMART-on-FHIR OAuth onboarding (FastAPI on Lambda) |
| `api/` | Practice dashboard API |
| `routing/` | Phone routing management |
| `audit/` | PHI audit logging |
| `infra/` | CDK app (TypeScript). Stacks in `infra/lib/`: connect, lex, phone-routing, practices, calls, api, audit, rate-limit |

## Conventions (non-obvious)

- **TDD always.** Write the failing test first, then implement. Tests live next to code (`<package>/tests/`).
- **No PHI in logs, ever.** Log `practice_id`, `call_id`, decisions taken — never patient data values. Audit-log PHI disclosures to the dedicated S3 bucket (see `docs/architecture.md`).
- **Secrets via Secrets Manager only.** No secrets in env vars at rest, no secrets committed. The `.env.example` files show the shape of env vars but never contain real values.
- **IaC for everything.** Anything created via the AWS console is a bug. The CDK app in `infra/` is the source of truth.
- **HIPAA-eligible services only.** Don't introduce a new AWS service without confirming it's HIPAA-eligible and adding it to the architecture doc.

## What this repo is

AWS-native voice agent for patient verification + three other resolve-the-call FHIR use cases (lab/imaging status, visit summary, document/referral status), on inbound calls, integrated with Practice Fusion's FHIR R4 endpoint via SMART-on-FHIR OAuth (Provider App, user scopes). One pilot practice, then scale to 20K.

**Architecture (ADR-0019):**

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

Each practice gets a dedicated DID; the router Lambda maps DID → `pf_org_uuid` via the `phone_routing` table (ADR-0014). Per-practice FHIR base URL + OAuth tokens are looked up by `pf_org_uuid`. The code-hook Lambda is an LLM-powered agent: Claude receives the verification prompt and conversation history every turn, decides what to say and when to call tools (ADR-0019). Lex + Nova 2 Sonic handle speech I/O only.

## What this repo is NOT (in v1)

- Not Amazon Connect Health prebuilt agents (PF is not a named partner). We integrate with Connect ourselves.
- Not an IVR / phone tree. The code-hook Lambda calls Claude every turn for natural conversation (ADR-0019). If it sounds like "press 1 for...", something is broken.
- Not AMAZON.BedrockAgentIntent (undocumented with Nova Sonic; see ADR-0019 evaluation).
- Not the (non-existent) "Connect native AI agent" with `InvokeAIAgent` block.
- Not Amazon Q in Connect text-AI agents (`qconnect:CreateAIAgent` / `AWS::Wisdom::AIAgent`).
- Not a custom AgentCore Runtime / Strands agent loop.
- `pf_org_uuid` is the practice key everywhere. No invented `practice_id`.
- No appointment management, refills, clinical Q&A, or EHR write-back in v1.
