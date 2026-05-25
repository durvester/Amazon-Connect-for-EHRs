# Session 0011 — Evaluation & Forward Session Plan

**Date:** 2026-05-24

This is the honest assessment of where we are, what's broken, what's
missing, and what the next 6 sessions should deliver.

---

## 1. What We Have (Verified Working)

### Proven against live PF QA
- **SMART-on-FHIR OAuth** — authorization_code + PKCE + refresh flow
- **lookup_patient** — 6-format phone probing, 401 retry + refresh, audit per probe, rate limiting
- **Token store** — KMS-encrypted, handles refresh rotation, marks `needs_reconnect`
- **Audit logging** — S3 Object Lock, one record per FHIR call, PHI-free schema
- **Rate limiting** — per-(practice, ANI) daily budget, atomic DDB increment

### Deployed to AWS (4 stacks, CREATE_COMPLETE)
- `pf-voice-qa-audit` — S3 bucket with Object Lock
- `pf-voice-qa-rate-limit` — DDB table
- `pf-voice-qa-phone-routing` — DDB table
- `pf-voice-qa-agent-gateway` — Gateway + lookup_patient Lambda

### Built this session, not yet deployed
- **Router Lambda** — DID → practice_id, 4 tests
- **Lex stack** — Nova 2 Sonic, VerifyAndResolve intent, code-hook config, 9 tests
- **Connect stack (rewritten)** — correct flow actions, 8 tests
- **Code-hook Lambda skeleton** — delegates on dialog, stubs on fulfillment, 7 tests

### Test health
- 153 Python tests, 43 CDK jest tests, all passing
- `make test-ci-unit` GREEN

---

## 2. What's Broken or Wrong (Must Fix Before Deploy)

### 2a. Contact flow has no UNKNOWN-DID branch

**The bug:** When the router returns `practice_id: "UNKNOWN"`, the flow
proceeds to `UpdateContactAttributes` and then to the Lex bot. The caller
hears the verification dialog for a practice that doesn't exist.

**Fix:** Add a `CheckContactAttributes` action (or equivalent branch)
after `set-practice-id` that checks if `practice_id == "UNKNOWN"` and
routes to a "this number is not in service" message + disconnect.

**Verify:** The flow language must have a conditional branch action. Need
to confirm the exact type name — likely `Compare` or a Conditions block
on the `UpdateContactAttributes` transition. Research needed before coding.

### 2b. Contact flow has no post-Lex routing

**The bug:** After the Lex conversation ends (intent closed), the flow
goes straight to `DisconnectParticipant`. There's no branching to route
verified callers to the human queue or escalated callers to the
escalation queue.

**Fix:** After `ConnectParticipantWithLexBot`, add actions to read the
Lex intent result (the intent name that completed) and route accordingly:
- VerifyAndResolve (Fulfilled) → transfer to verified queue
- FallbackIntent → transfer to escalation queue
- Error/timeout → disconnect with message

**Dependency:** Connect must have at least two queues configured. This is
likely a console/CDK action — `AWS::Connect::Queue`.

### 2c. lookup_patient env vars are empty strings in the Gateway stack

**The bug:** `infra/lib/agent-gateway-stack.ts` line 70-76 — the
lookup_patient Lambda has placeholder empty-string env vars:

```typescript
PF_PRACTICES_TABLE: "",
PF_TOKEN_TABLE: "",
PF_RATE_LIMIT_TABLE: "",
PF_AUDIT_BUCKET: "",
PF_TOKEN_KMS_KEY_ARN: "",
```

These need to be wired to real stack outputs. But the stacks that create
these tables (audit, rate-limit) are separate CDK stacks. Cross-stack
references need to be plumbed through `app.ts`.

**Fix:** Pass table names and bucket ARN from the audit, rate-limit,
and (future) practices stacks into the agent-gateway stack props.

**Note:** The env var names in the Lambda code (`PRACTICES_TABLE_NAME`,
`TOKENS_TABLE_NAME`, etc.) don't match the CDK env var names
(`PF_PRACTICES_TABLE`, `PF_TOKEN_TABLE`, etc.). This will cause
`KeyError` at runtime. Must reconcile.

### 2d. Code-hook fulfillment is a stub

**The current state:** The fulfillment handler returns a hardcoded
"Thank you, I have your information" message. It doesn't call
lookup_patient.

**Design question:** Should the code-hook call lookup_patient:
- **(A) Directly** — the code-hook Lambda already bundles the
  lookup_patient package. It can import and call `handler()` directly.
  Simpler, lower latency, no extra Lambda invocation.
- **(B) Via AgentCore Gateway** — the published architecture (ADR-0012)
  says tools are consumed via Gateway. The code-hook would make an MCP
  call to the Gateway, which invokes the lookup_patient Lambda.
  More hops, higher latency, but consistent with the MCP catalog model.
- **(C) Via Lambda invoke** — the code-hook invokes the lookup_patient
  Lambda directly using `boto3.client('lambda').invoke()`. The Gateway
  is not in the path, but the tool Lambda runs in its own execution
  context with its own env vars / permissions.

**Recommendation:** **(A) Direct import** for v1. The code-hook already
bundles lookup_patient. The Gateway exists for external MCP consumers
(future dashboard, future chat surface). The code-hook is an internal
consumer — adding a Gateway hop adds ~500ms latency and a failure point
for no v1 benefit. We can revisit when we have a second MCP consumer.

**But this means:** The code-hook Lambda needs the same env vars and IAM
permissions as the lookup_patient Lambda (DDB access for practices,
tokens, rate-limit; S3 for audit; KMS for token decryption; Secrets
Manager for client_secret).

### 2e. The code-hook doesn't handle disambiguation

**The current state:** When lookup_patient returns `multiple_matches`,
the code-hook has no logic to re-elicit a slot (e.g., ask for last-4 of
phone number). It would need to return `ElicitSlot` with a new slot
definition — but the bot currently has no slot for phone disambiguation.

**Fix:** Either:
- Add a `PhoneLastFour` slot to the VerifyAndResolve intent (optional,
  only elicited when disambiguation is needed)
- Or use the `messages` field on the `ElicitSlot` response to ask
  freeform and parse the response in the next dialog hook

**This is the ADR-0018 kill criterion test.** If Lex can't handle this
flow naturally, we revisit Path B (BedrockAgentIntent).

---

## 3. What's Missing (Not Built At All)

| Gap | Impact | Priority |
|---|---|---|
| **Connect queues** (verified + escalation) | Calls can't be transferred to humans | P0 — must have for any real call |
| **TransferContactToQueue flow action** | Contact flow can't route to queues | P0 |
| **practices / oauth-tokens DDB tables (CDK)** | lookup_patient can't resolve credentials | P0 — tables exist in code but not in CDK stacks |
| **KMS CMKs (CDK)** | Token store can't encrypt/decrypt | P0 |
| **Code-hook → lookup_patient wiring** | Verification doesn't actually verify | P0 |
| **Disambiguation flow** | Multiple-match calls fail | P1 |
| **Post-verification JTBD tools** (lab, visit, doc) | Can't resolve calls — just transfer | P2 |
| **After-hours handling** | All calls treated as business hours | P2 |
| **Dashboard** (Cognito, React, calls API) | Maria can't see call outcomes | P2 |
| **CloudWatch alarms** | Nobody knows when things break | P2 |
| **Call recording config** | No transcript/audio capture | P2 |
| **Cognito for practice auth** | No secure onboarding | P3 (manual for pilot) |

### Critical missing CDK resources

The architecture doc defines `practices` and `oauth-tokens` DDB tables
and KMS CMKs, but **no CDK stack creates them**. The OAuth onboarding
API writes to them (Session 0008), but the tables are created by... nobody.
This is a gap from Session 0006-0008 — the code uses the tables, but
the IaC doesn't provision them.

**Fix:** New `PracticesStack` (or extend `ApiStack`) to create:
- DDB: `practices` table (PK: practice_id)
- DDB: `oauth-tokens` table (PK: practice_id)
- DDB: `oauth-state` table (PK: state, TTL on ttl field)
- KMS: `oauth-key` CMK
- Cross-stack grants to the API Lambda and the code-hook/lookup Lambda

---

## 4. What Needs Rethinking

### 4a. The Lex slot model might be too rigid

The user journey shows James saying "hi, I'm calling about my lab
results." But Lex will respond with "Could I get your first name?" —
a rigid slot elicitation sequence. Natural conversation would be:

> **James:** "Hi, I'm calling about my lab results."
> **AI:** "I'd be happy to help with that. First, I need to verify your
>          identity. Could you tell me your name?"

Lex's slot model will handle the verification part, but the transition
from "reason for calling" to "verification" is awkward. The AI doesn't
acknowledge what the caller said — it just starts asking for slots.

**Mitigation for v1:** Make the first Lex prompt acknowledge the caller's
intent: "Thank you for calling. Before I can help you, I need to verify
your identity. Could I get your first name?" This is a static prompt —
it doesn't actually parse what the caller said. It's honest ("I need to
verify first") even if not conversational.

**Long-term:** `AMAZON.BedrockAgentIntent` (Path B) would handle this
naturally. The Bedrock Agent would understand "I'm calling about labs"
and respond conversationally while still driving the verification flow.

### 4b. The code-hook calling lookup_patient directly breaks the MCP model

If the code-hook imports lookup_patient directly (recommendation 2d-A),
then the AgentCore Gateway stack's lookup_patient Lambda is unused for
the call path. The Gateway becomes a catalog-only construct with no
runtime traffic.

**This is fine for v1** — the Gateway still serves as the MCP contract
(tool_schema.json) and is the integration surface for future consumers.
But it means we have two copies of lookup_patient running:
1. The Gateway Lambda (with its own env vars, currently empty)
2. The code-hook Lambda (which bundles lookup_patient and needs real env vars)

**Decision:** Accept this for v1. The Gateway Lambda env vars should still
be wired (for future use and for direct testing), but the call-path flows
through the code-hook Lambda.

### 4c. Env var naming inconsistency

lookup_patient handler reads: `PRACTICES_TABLE_NAME`, `TOKENS_TABLE_NAME`,
`OAUTH_KMS_KEY_ARN`, `AUDIT_BUCKET_NAME`, `RATELIMIT_TABLE_NAME`.

CDK agent-gateway stack sets: `PF_PRACTICES_TABLE`, `PF_TOKEN_TABLE`,
`PF_TOKEN_KMS_KEY_ARN`, `PF_AUDIT_BUCKET`, `PF_RATE_LIMIT_TABLE`.

These don't match. The Lambda will crash at runtime. Must reconcile to
one set of names.

---

## 5. Revised Session Plan

### Session 0012: Wire It + Deploy + First Real Call

**Objective:** Get a phone number that rings, verifies a caller against
PF QA, and either confirms or transfers. This is the ADR-0018 kill
criterion test.

**Deliverables:**
1. **Fix env var naming** — reconcile CDK and Lambda env var names
2. **Create PracticesStack** — DDB tables for practices, oauth-tokens,
   oauth-state; KMS `oauth-key` CMK
3. **Wire cross-stack references** — pass table names / ARNs from
   practices, audit, rate-limit stacks into agent-gateway and lex stacks
4. **Wire code-hook → lookup_patient** — direct import, not Gateway.
   Map lookup_patient result statuses to Lex dialog actions:
   - `candidates` (1 match) → Close(Fulfilled) + "I've verified you"
   - `candidates` (0 matches) → Close(Failed) + "I couldn't find..."
   - `candidates` (2+ matches) → store in session, ElicitSlot for phone last-4
   - `rate_limited` / `credentials_expired` / `error` → Close(Failed) + escalate message
5. **Fix contact flow**:
   - Add UNKNOWN-DID branch (check practice_id, disconnect if UNKNOWN)
   - Add post-Lex routing (check intent result, transfer to queue or disconnect)
6. **Create Connect queues** — verified-callers + escalation
7. **Deploy all stacks** (7-8 stacks depending on PracticesStack)
8. **Run one onboarding** against PF QA
9. **Make one test call** — dial DID, verify, hear result
10. **Evaluate Lex conversation quality** — is the slot model too rigid?

**Exit criteria:**
- All stacks deployed
- One verified call end-to-end
- Lex conversation quality assessment documented (go/no-go on slot model)
- `make test-ci` green

**Kill criterion check:** If Lex's slot model makes the conversation
feel robotic to the point where callers would hang up, document the
problem and plan the Path B migration for Session 0013.

### Session 0013: Conversation Hardening + Eval Harness

**Objective:** Based on Session 0012's findings, either harden the Lex
slot model or pivot to BedrockAgentIntent. Plus: build the eval harness
ADR-0013 calls for.

**Deliverables:**
- Disambiguation flow (multiple matches → ask for phone last-4)
- All edge cases from user-journeys.md handled
- After-hours branching in contact flow
- Eval corpus: ≥20 scripted conversations with expected outcomes
- Verdict-stability measurement (ADR-0013: target ≥99%)

### Session 0014: lab_result_status tool

**Prerequisite:** 30-min data-quality spike against PF QA for
DiagnosticReport resources. If PF QA has none, seed test data first.

**Deliverables:**
- New tool: `tools/lab_result_status/` (Lambda + tests)
- Code-hook integration (after verification, route "lab results" queries)
- Voice-readback rules (one item, offer "N more")

### Session 0015: visit_summary + document_status tools

**Prerequisite:** 30-min spike each for CarePlan and DocumentReference.

**Deliverables:** Two tools following the lab_result_status pattern.
Combined into one session because the scaffold is now established.

### Session 0016: Dashboard MVP

**Deliverables:**
- Cognito user pool + CDK stack
- React pages: login, call list (from calls DDB table), practice status
- API endpoints: `GET /calls`, `GET /practice/{id}/status`
- Practice can see call outcomes, verify connection status

### Session 0017: Observability + Pilot Cutover Prep

**Deliverables:**
- CloudWatch alarms (token refresh failure, error rate, rate-limit hits)
- CloudWatch dashboard (per-practice call volume, verification rate)
- Call recording config in Connect
- Practice onboarding runbook
- Pilot go/no-go checklist

---

## 6. Summary: Where We Actually Are

**Honest assessment:** We have a solid FHIR integration backend (Sessions
0001-0006 were clean) and a correct-but-skeleton voice surface (Session
0011). The three sessions of architectural error (0007-0009) were caught
and corrected. The main risk is no longer "is the architecture right?" —
it's "does the conversation feel right?" That's what Session 0012's test
call will answer.

**What I'm most confident about:** The OAuth flow, token management,
audit logging, and rate limiting. These are production-shaped and tested
against live PF QA.

**What I'm least confident about:** The Lex slot model's conversational
quality with Nova 2 Sonic. The user journey document makes this gap
visible — a real caller doesn't say "first name: James, last name:
Wilson, DOB: March 15 1982." They say "hey, I'm calling about my labs,
this is James Wilson." Lex will handle the slot collection, but the
*feel* of the conversation is unknown until we hear it.

**The one thing that matters most right now:** Session 0012's test call.
Everything else is downstream of whether the voice surface works.
