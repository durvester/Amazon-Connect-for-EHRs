# Architecture

This document is the **current** target architecture. If you change the architecture, write a new ADR in `decisions/` and update this file in the same commit.

> **Session 0011 final (2026-05-24).** ADR-0019 + ADR-0020. The code-hook
> Lambda calls Claude via Bedrock InvokeModel every turn — it's an LLM-
> powered agent, not an IVR. Lex is speech I/O (Nova 2 Sonic) + turn-
> taking plumbing. `pf_org_uuid` is the practice identity key everywhere
> (ADR-0020). Supersedes the rigid-slot design from earlier in Session 0011.

## The call flow

```
 1. CALL ARRIVES — patient dials practice's dedicated DID (ADR-0014).
       │
       ▼
 2. CONTACT FLOW:
      - InvokeLambdaFunction → router Lambda reads `phone_routing`
        by $.SystemEndpoint.Address → returns pf_org_uuid
      - If pf_org_uuid == "UNKNOWN" → play message → disconnect
      - UpdateContactAttributes: pf_org_uuid
      - ConnectParticipantWithLexBot → Lex bot (Nova 2 Sonic)
        with pf_org_uuid passed as Lex session attribute
       │
       ▼
 3. LEX BOT (Nova 2 Sonic speech-to-speech at locale level):
      - Single FallbackIntent catches every utterance
      - FulfillmentCodeHook fires every turn → code-hook Lambda
      - Code-hook returns ElicitIntent + message → loop continues
      - Code-hook returns Close → conversation ends → back to flow
       │
       ▼
 4. CODE-HOOK LAMBDA (the agent brain; ADR-0019):
      Every turn:
      a. Read inputTranscript (caller's words) from Lex event
      b. Append to conversation history (Lex session attributes)
      c. Call Bedrock InvokeModel (Claude Sonnet) with:
           - System prompt: agent/prompts/verification.md
           - Conversation history
           - Tool definitions: lookup_patient, lab_result_status, etc.
      d. If Claude requests a tool call → execute it directly →
         feed result back to Claude
      e. Return ElicitIntent + Claude's text → Nova Sonic speaks it
      f. When done → Close(Fulfilled/Failed) → back to contact flow
       │
       ▼  (direct Lambda import; Gateway is for external MCP consumers)
 5. TOOL LAMBDA (thin FHIR adapter; ADR-0013):
      - Rate-limit gate keyed on (pf_org_uuid, ANI, day-bucket)
      - Resolve per-practice credentials; refresh on near-expiry or 401
      - Probe PF FHIR (ADR-0006 literal-telecom rule)
      - Write one disclosure record per FHIR probe (ADR-0009)
      - Return { status, candidates, probes_tried }
       │
       ▼
 6. PRACTICE FUSION FHIR R4 (per-practice base URL).
```

The key handoffs:

- **Contact flow → router Lambda:** `InvokeLambdaFunction` (8s max
  timeout). Router does a single DDB GetItem — p99 < 100ms.
- **Contact flow → Lex bot:** `ConnectParticipantWithLexBot`. `pf_org_uuid`
  is passed via `LexSessionAttributes` so the code-hook Lambda has it.
- **Lex → code-hook Lambda:** FallbackIntent fulfillmentCodeHook. Fires
  every turn. Code-hook returns `ElicitIntent` (continue) or `Close` (done).
- **Code-hook → Claude:** Bedrock InvokeModel. ~1-3s per turn. The
  verification prompt from `agent/prompts/verification.md` is the system
  prompt. Claude decides what to say and when to call tools.
- **Code-hook → lookup_patient:** Direct import (both in same Lambda
  package). No Gateway hop for the call path. Gateway remains for
  external MCP consumers.
- **Code-hook Lambda → AgentCore Gateway:** MCP tool invocation for
  FHIR lookups. 30s per-tool timeout (ADR-0012).

## Component map

| Component | AWS service / library | Purpose |
|---|---|---|
| Telephony | Amazon Connect | Inbound DID per practice, contact flow |
| Voice + speech | Lex V2 bot with Nova 2 Sonic (`UnifiedSpeechSettings`) | Bidirectional speech-to-speech; slot collection |
| Dialog orchestration | Lex code-hook Lambda | Verification logic, FHIR tool invocation, conversation state |
| DID → practice_id router | Router Lambda + DynamoDB `phone_routing` (ADR-0014) | Read at every call start via `InvokeLambdaFunction` |
| Tool catalog | Bedrock AgentCore Gateway | Exposes our Lambdas as MCP tools; ToolSchema as contract (ADR-0012) |
| Tool: `lookup_patient` | Python Lambda + `tool_schema.json` | Calls Practice Fusion FHIR `Patient?telecom=&birthdate=` (ADR-0006) |
| Tool: `lab_result_status` (future) | Python Lambda + `tool_schema.json` | DiagnosticReport status query |
| Tool: `visit_summary` (future) | Python Lambda + `tool_schema.json` | Encounter + active CarePlan summary |
| Tool: `document_status` (future) | Python Lambda + `tool_schema.json` | DocumentReference status query |
| Practice config | DynamoDB table `practices` | `practice_id → {fhir_base_url, token_endpoint, pf_client_id, pf_client_secret_arn}` |
| OAuth tokens | DynamoDB table `oauth-tokens` | KMS-encrypted access + refresh tokens, one row per practice |
| OAuth state cache | DynamoDB table `oauth-state` (TTL-evicted; ADR-0016) | Single-use PKCE/state row between `/oauth/start` and `/oauth/callback` |
| Secrets | AWS Secrets Manager | One PF Provider App `client_secret` per env (ADR-0016) |
| Per-(practice, ANI) rate-limit | DynamoDB table `rate-limit` (TTL-evicted) | Daily call budget per (practice, ANI) |
| OAuth onboarding API | Python FastAPI on Lambda + Function URL (ADR-0015) | `/oauth/start`, `/oauth/callback`; on success, claims a Connect DID + writes the `practices` / `oauth-tokens` / `phone_routing` rows in one shot |
| Practice API (later) | Python FastAPI on Lambda + API Gateway | Backend for the dashboard |
| Practice dashboard (later) | React + Vite + TypeScript | Hosted on CloudFront + S3 |
| Auth (dashboard) | Amazon Cognito | One user per practice-staff member |
| Call recordings + transcripts | S3 (KMS-CMK encrypted) | Per-call artifacts |
| PHI disclosure audit log | S3 with object-lock + KMS-CMK | HIPAA Accounting of Disclosures (ADR-0009) |
| IaC | AWS CDK (TypeScript), env-context per ADR-0008 | All infra as code; no console state |

## Data model

### `practices` table (DynamoDB)

| Field | Type | Notes |
|---|---|---|
| `practice_id` (PK) | string | Our internal identifier |
| `pf_org_uuid` | string | Practice Fusion's org UUID — substituted into the FHIR base URL |
| `fhir_base_url` | string | Full base URL: `https://api.practicefusion.com/fhir/r4/v1/{pf_org_uuid}` |
| `pf_client_secret_arn` | string | Secrets Manager ARN for the practice's `PF_CLIENT_SECRET` |
| `pf_client_id` | string | OK to store in DDB (not a secret) |
| `verification_factors` | string set | Subset of `{phone, dob, zip, ssn_last4}`; minimum `{phone, dob}` |
| `connect_queue_arn` | string | Where verified callers are routed |
| `connect_escalate_queue_arn` | string | Where unverified callers go |
| `business_hours` | map | Per-day open hours (used for after-hours messaging) |
| `created_at` / `updated_at` | string | ISO-8601 |

### `oauth-tokens` table (DynamoDB)

| Field | Type | Notes |
|---|---|---|
| `practice_id` (PK) | string | One token row per practice |
| `refresh_token_ciphertext` | binary | KMS-encrypted (envelope via DDB SSE-KMS + app-layer KMS Decrypt) |
| `access_token_ciphertext` | binary | Cached access token (when still valid) |
| `expires_at` | number | Epoch seconds — access-token expiry |
| `refresh_expires_at` | number | Epoch seconds — refresh-token expiry |
| `last_refreshed_at` | number | Epoch seconds |
| `status` | string | `active` | `needs_reconnect` |

### `calls` table (DynamoDB)

| Field | Type | Notes |
|---|---|---|
| `practice_id` (PK) | string | Partition by practice for tenancy |
| `call_id` (SK) | string | Connect contact ID |
| `started_at` | string | ISO-8601 |
| `ended_at` | string | ISO-8601 |
| `caller_phone_masked` | string | E.164 with middle digits masked (`+1***5551234`) |
| `verification_outcome` | string | `verified` \| `escalated` \| `failed` \| `hung_up` |
| `verified_patient_id` | string | FHIR resource ID if verified; never the patient's data |
| `transcript_s3_key` | string | KMS-encrypted transcript object |
| `audio_s3_key` | string | KMS-encrypted audio object |
| `tool_calls` | list | Structured timeline of tool invocations (no PHI values) |
| `routed_to_queue_arn` | string | Final routing destination |

## SMART-on-FHIR OAuth flow (Provider App, user scopes)

```
   ┌────────────────────────────────────────────────────────────┐
   │  ONE-TIME PER PRACTICE — Onboarding                        │
   │                                                            │
   │  1. Provider logs into our dashboard (Cognito)             │
   │  2. Clicks "Connect Practice Fusion"                       │
   │  3. We GET {fhir_base_url}/.well-known/smart-configuration │
   │     to discover authorization_endpoint, token_endpoint     │
   │  4. Generate PKCE verifier + challenge, state param        │
   │  5. Redirect provider to PF's authorization_endpoint:      │
   │       ?response_type=code                                  │
   │       &client_id={PF_CLIENT_ID}                            │
   │       &scope={user/Patient.read openid fhirUser            │
   │              offline_access}                               │
   │       &redirect_uri=https://api.<host>/oauth/callback      │
   │       &state={state}&code_challenge={pkce}                 │
   │       &code_challenge_method=S256                          │
   │  6. Provider signs into PF, grants scopes                  │
   │  7. PF redirects back to our /oauth/callback?code=&state=  │
   │  8. We exchange code for access_token + refresh_token      │
   │  9. Store refresh_token (KMS-encrypted) in DDB             │
   └────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────┐
   │  AT EVERY CALL — Runtime                                   │
   │                                                            │
   │  1. Code-hook Lambda (or tool Lambda) reads practice tokens│
   │  2. If access_token still valid, use it                    │
   │  3. Else: POST to token_endpoint with refresh_token,       │
   │     mint a new access_token, update DDB                    │
   │  4. Call {fhir_base_url}/Patient?telecom=&birthdate=       │
   │     with Authorization: Bearer {access_token}              │
   └────────────────────────────────────────────────────────────┘
```

**Validated (ADR-0007):** PF accepts user-scope refresh tokens for
unattended (phone-time) reads. No pivot to Backend Services needed.

## Security model

- **HIPAA-eligible services only.** Every service in the stack is on the AWS HIPAA-eligible list. Verify BAA covers account `086514900943` via AWS Artifact before any PHI flows.
- **Customer-managed KMS keys for PHI.** Two CMKs:
  - `phi-key` — used for S3 (transcripts, audio, audit log), DynamoDB `calls` table
  - `oauth-key` — used for the OAuth-token storage and envelope-encryption of refresh tokens
- **Least-privilege IAM.** One execution role per Lambda; each role references the specific resources it needs by ARN. No `*` resources.
- **Secrets only in Secrets Manager.** Never in env vars at rest. Lambda fetches at cold-start, caches in memory.
- **Structured logging — no PHI.** Logs include `practice_id`, `call_id`, decisions taken, tool names, timing — never the patient's data values.
- **Audit log per PHI disclosure.** Separate S3 bucket with Object Lock (compliance mode), one record per `Patient` read with: `practice_id`, `call_id`, timestamp, `patient_resource_id`, fields accessed. Required for HIPAA Accounting of Disclosures.
- **No PHI before verification.** The verification prompt forbids revealing any patient data until verification succeeds. The tool-return is the source of truth — the LLM cannot self-declare verification.
- **Per-tenant data isolation.** Every API endpoint and Lambda enforces `practice_id` scoping. Cognito JWT carries the practice claim.

## Observability

- **X-Ray** tracing on every Lambda.
- **CloudWatch dashboards** (built in CDK): per-practice call volume, verification success rate, p95 turn latency, Bedrock error rates, OAuth refresh failures.
- **Synthetic monitoring** (planned): every 5 min, a synthetic call exercises the flow.

## What's intentionally simple

- **One DynamoDB table per concern.** No fancy single-table design until we know the access patterns.
- **Lex intent model is minimal.** One VerifyAndResolve intent with three slots. The code-hook Lambda handles the conversation complexity, not Lex's intent classification.
- **Four tools.** Not "an SDK of FHIR operations" — explicit, minimal tools.
- **One region (us-east-1).** Multi-region waits until we have real production traffic to justify the operational cost.

## Alternative path: AMAZON.BedrockAgentIntent (documented, not chosen for v1)

Session 0011 research discovered `AMAZON.BedrockAgentIntent` — a Lex
built-in intent that delegates conversation to a Bedrock Agent. This
could replace the code-hook Lambda with a Bedrock Agent that natively
handles multi-turn dialog and tool calling. Documented in
`docs/architecture-jtbd.md` as Path B. Not chosen for v1 because:
compatibility with Nova Sonic `UnifiedSpeechSettings` is unverified, and
the code-hook path is the safer bet. If code-hook rigidity becomes a
problem (ADR-0018 kill criterion), Path B is the fallback.
