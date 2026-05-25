# Session 0012 — LLM-powered code-hook, PracticesStack, first live calls

**Date:** 2026-05-24
**Goal:** Rewrite the code-hook Lambda to call Claude every turn (ADR-0019),
deploy the full voice pipeline, and make a real phone call that verifies a patient.

## What was done

### Phase 1: Code + Infrastructure (first half)

- **Code-hook Lambda rewrite (ADR-0019):** replaced rigid slot logic with
  LLM agent loop. Every utterance → Bedrock InvokeModel (Claude Sonnet 4.6)
  with verification prompt + conversation history. Tool execution inline
  (lookup_patient, escalate_to_human). 9 tests.

- **PracticesStack (new):** DDB tables for practices + oauth-tokens, KMS CMK
  for token encryption. 5 CDK tests.

- **pf_org_uuid rename (ADR-0020):** router Lambda, contact flow, session
  attributes all renamed. 4 router tests updated.

- **Lex bot simplified:** FallbackIntent only (later fixed — see Phase 2).

### Phase 2: Pre-deploy audit (critical bugs found and fixed)

Verified 8 items against primary-source AWS docs. Found and fixed:

1. `anthropic_version` wrong → `bedrock-2023-05-31`
2. `MessageParticipant` vs `PlayPrompt` — tested both via CLI, `MessageParticipant` works
3. `CheckContactAttributes` → `Compare` with `Operator/Operands` format
4. Session attributes 12KB limit is pre-base64 (~9KB effective) → lowered MAX_TURNS, added truncation
5. Verification prompt excluded from Lambda bundle → copied to package
6. Claude Sonnet 4 (20250514) LEGACY → updated to `us.anthropic.claude-sonnet-4-6`
7. API stack Docker bundling broken → removed local-only PyPI deps from api/pyproject.toml
8. `ConnectParticipantWithLexBot` requires `Text` param → added greeting

### Phase 3: Deploy + live debugging

Deployed 7/8 stacks. Then iterative live call debugging:

| Problem | Root cause | Fix |
|---------|-----------|-----|
| Immediate hangup | Lex bot locale failed to build (FallbackIntent-only has no utterances) | Added VerificationAgent intent with sample utterances |
| "Problem connecting to AI agent" | Lex bot not associated with Connect instance (lost on stack recreate) | CLI `associate-bot` + `associate-phone-number-contact-flow` |
| "Problem connecting to AI agent" (again) | `inputTranscript` empty on first turn → Bedrock rejects empty text | Guard: `[caller just connected]` placeholder |
| Verification → "connect to human" | oauth-tokens table empty → `credentials_expired` | Seeded refresh token from pf-qa-tokens.json with KMS encryption |
| Verification → "connect to human" (audit error) | Code-hook Lambda missing `kms:GenerateDataKey` on audit bucket KMS key | CLI inline IAM policy (now in CDK) |
| **SUCCESS: Mohit Durve verified** | Token refresh worked, FHIR Patient search found match, Claude confirmed identity | — |
| Nishant Salvi NOT found | lookup_patient always searches `telecom=<ANI>&birthdate=<DOB>` — Nishant's record doesn't have the caller's phone | Known limitation — `fhir_query` tool will fix with `family+given+birthdate` fallback |
| Empty transcript mid-conversation | History saved raw `inputTranscript` including empty strings → Bedrock rejects on next turn | Guard empty strings in history save (deployed) |

### Phase 4: CDK reconciliation

Updated CDK to match deployed reality:
- `lex-stack.ts`: VerificationAgent intent replaces PlaceholderIntent, audit KMS key added to IAM grants
- `connect-stack.ts`: flow content matches deployed flow (MessageParticipant error messages, all branches)
- `app.ts`: passes auditKmsKeyArn to LexStack
- All tests updated and passing (19 CDK tests for lex+connect)
- Deployed successfully — CDK diff showed only expected changes

### Phase 5: Architecture planning

Planned Session 0013: single `fhir_query` tool that lets Claude compose
FHIR queries flexibly (labs, meds, encounters, documents). Guardrails
split: code enforces allowlists + projections + audit; prompt controls
what Claude says aloud.

## Decisions made

- **VerificationAgent intent, not PlaceholderIntent:** Lex requires at
  least one custom intent with utterances. VerificationAgent with generic
  utterances (hello, I need help, etc.) is the correct design — both it
  and FallbackIntent route to the code-hook Lambda.
- **MessageParticipant confirmed working:** despite docs uncertainty,
  CLI testing proved `MessageParticipant` is a valid flow action Type.
- **Session attributes store conversation history as JSON:** with 9KB
  effective budget, MAX_TURNS=10, and truncation of oldest turns.
- **Bedrock Agent (HUCF0JUHIU) created but not in critical path:** the
  working architecture is Lex → code-hook Lambda → Bedrock InvokeModel.
  BedrockAgentIntent is a future option (ADR-0021 candidate).
- **`fhir_query` single tool > 5 specialized tools:** Claude composes
  queries; code enforces allowlists and projections. Approved for Session 0013.

## Open questions

1. **lookup_patient phone-only search is too rigid.** Nishant Salvi not
   found because search requires telecom match. The `fhir_query` tool
   should support `family+given+birthdate` search as fallback.
2. **Bedrock Agent path vs code-hook path.** Both exist. Code-hook is
   working and deployed. Bedrock Agent is created but not wired to Lex
   via BedrockAgentIntent (CLI doesn't support the parameter yet, CFN does).
   Decision deferred.
3. **11 CLI-created resources need CDK codification.** See CDK debt table below.

## CDK debt inventory

| # | Resource | In CDK? | Risk on redeploy |
|---|----------|---------|------------------|
| 1 | Lex VerificationAgent intent | YES (just fixed) | Low — CDK matches |
| 2 | Lex bot version 3 (alias target) | NO — alias points to CLI version | Medium — CDK creates version 1 |
| 3 | Connect bot association | NO | HIGH — lost on instance recreate |
| 4 | Connect Lambda association | NO | HIGH — same |
| 5 | Phone number claimed + flow association | NO (no CFN construct) | HIGH — manual step |
| 6 | Bedrock Agent HUCF0JUHIU | NO | Low — not in critical path |
| 7 | Agent action group Lambda | NO | Low — not in critical path |
| 8 | IAM role for Bedrock Agent | NO | Low |
| 9 | Audit KMS on code-hook Lambda | YES (just fixed) | Low — CDK matches |
| 10 | Escalation queue | NO | Medium — passed via context var |
| 11 | Contact flow content | YES (just reconciled) | Low — CDK matches |

## Test results

- **155+ Python tests:** all passing
- **50+ CDK jest tests:** all passing (19 for lex+connect)
- **CDK synth:** all 8 stacks synthesize
- **Live call tests:**
  - Mohit Durve, DOB 1991-06-09: **VERIFIED** ✓
  - Nishant Salvi, DOB 1993-07-28: **NOT FOUND** (phone probe limitation)

## Next session pickup

**Read these files first:**
1. `docs/sessions/0012-llm-code-hook-and-practices-stack.md` — this file
2. `/Users/m858450/.claude/plans/mutable-skipping-hearth.md` — approved Session 0013 plan
3. `tools/lex_code_hook/src/lex_code_hook/handler.py` — the working code-hook
4. `tools/lookup_patient/src/lookup_patient/fhir_client.py` — FHIR client patterns to reuse

**Session 0013 goal:** "I call, verify, ask about my labs, and get an answer."

**Session 0013 plan (approved):**

**Priority 0: CDK stability** (items 3-5 from debt table)
- Add Connect bot/Lambda association as custom resource or post-deploy script
- Document phone number claiming as manual step
- Verify `cdk deploy` doesn't break the working call

**Step 1: `fhir_query` tool** (TDD)
- New package `tools/fhir_query/` with handler, fhir_client, projections
- Single tool Claude can use to query any FHIR resource (DiagnosticReport, MedicationRequest, Encounter, CarePlan, DocumentReference, Observation)
- Code enforces: allowlisted resource types, allowlisted search params, patient_id matches verified patient, response projection strips clinical values, audit logging
- Also fix lookup_patient limitation: add `family+given+birthdate` search as fallback when phone probe returns zero

**Step 2: `patient_service.md` prompt** (two-phase)
- Phase 1: verification (current prompt, preserved)
- Phase 2: post-verification service (labs, meds, visits, documents)
- "Let me check on that for you" before every tool call (UX fix)

**Step 3: Code-hook handler updates**
- Add `fhir_query` + `complete_verification` tools
- `complete_verification` sets `verified_patient_id` in session
- `_MAX_TOOL_ROUNDS` → 5
- Deploy + TEST WITH CALL

**Step 4: Test with multiple patients and questions**
- Verify as Mohit → "Are my labs back?" → answer
- Verify as Nishant (via name+DOB search) → "What medications am I on?"

**Key user feedback to honor:**
- Test at every stage with real calls, not just unit tests
- No hacks or fallbacks — TDD everything
- Build dev/sandbox same as GA (proper onboarding flow, not manual seeding)
- Let the model do its magic — flexible tools with guardrails in prompt + projections

**Pass/fail:**
- PASS: Two different patients verified, post-verification FHIR query answered
- FAIL: Any patient can't verify, or clinical values spoken aloud, or >60s total

## Files changed

- `tools/lex_code_hook/src/lex_code_hook/handler.py` — complete rewrite + iterative fixes
- `tools/lex_code_hook/src/lex_code_hook/prompts/verification.md` — v2.0
- `tools/lex_code_hook/tests/test_handler.py` — 9 tests
- `tools/lex_code_hook/pyproject.toml` — package-data for prompt
- `tools/lex_code_hook/src/lex_code_hook/prompts/verification.md` — bundled prompt
- `tools/router_lookup/src/router_lookup/handler.py` — pf_org_uuid rename
- `tools/router_lookup/tests/test_handler.py` — updated
- `tools/escalate_to_human/src/escalate_to_human/handler.py` — implemented (was stub)
- `tools/escalate_to_human/tests/test_handler.py` — 3 tests
- `tools/agent_action_group/` — new package (Bedrock Agent action group)
- `infra/lib/lex-stack.ts` — VerificationAgent intent, audit KMS, model ID
- `infra/lib/connect-stack.ts` — flow content reconciled, MessageParticipant, escalation routing
- `infra/lib/practices-stack.ts` — new (DDB + KMS)
- `infra/bin/app.ts` — PracticesStack wiring, audit KMS, escalation queue context
- `infra/test/lex-stack.test.ts` — updated for VerificationAgent
- `infra/test/connect-stack.test.ts` — updated for reconciled flow
- `infra/test/practices-stack.test.ts` — new (5 tests)
- `agent/src/agent/prompts/verification.md` — v2.0
- `api/pyproject.toml` — removed local-only deps (fixed Docker bundling)

## Notes for future Claude

- **`MessageParticipant` IS a valid Connect flow action Type.** Despite
  the research agent saying it wasn't, CLI testing confirmed it works.
  `PlayPrompt` also exists but wasn't tested. Use `MessageParticipant`
  for TTS messages in the flow.

- **Lex requires at least one custom intent with utterances.** A bot
  with only FallbackIntent fails locale build. The VerificationAgent
  intent with generic utterances (hello, I need help) is the solution.

- **CDK deploys don't manage Connect bot/Lambda associations or phone
  numbers.** These must be re-applied after any stack recreate:
  ```
  aws connect associate-bot --instance-id <ID> --lex-v2-bot AliasArn=<ARN>
  aws connect associate-lambda-function --instance-id <ID> --function-arn <ARN>
  aws connect associate-phone-number-contact-flow --phone-number-id <ID> --instance-id <ID> --contact-flow-id <ID>
  ```

- **The Lex bot alias points to version 3 (CLI-created), not CDK version 1.**
  CDK manages the DRAFT + creates versions, but the alias was manually
  pointed to version 3. On next CDK deploy, verify the alias still works.

- **Empty `inputTranscript` happens in two scenarios:** (1) initial Lex
  greeting before user speaks, (2) silence/noise mid-conversation. Both
  are guarded with `[caller just connected]` / `[silence]` placeholders.
  These must be guarded in both `_build_messages` AND history save.

- **Pilot practice data:**
  - `pf_org_uuid`: `b4ab304f-d1ac-4565-8dca-992b589422a7`
  - Phone number: `+16156250631` (Nashville DID)
  - Connect instance: `bc48ce14-1766-44c9-807b-4807e6010dd6`
  - Lex bot: `Q8KEE7VWFQ` / alias `HI8OESGPSF` (version 3)
  - Bedrock Agent: `HUCF0JUHIU` / alias `YNYTKBVNVU` (not in critical path)
  - Escalation queue: `56d2736b-5e63-454f-b01b-52591e650a55`
  - Contact flow: `7d44dd04-a8dc-4059-95dd-51bb471be059`

- **oauth-tokens seeded manually** from `secrets/pf-qa-tokens.json` with
  `expires_at=0` (forces refresh on first call). The refresh flow works —
  confirmed by successful FHIR calls after token refresh.

- **lookup_patient phone-only search limitation:** searches
  `Patient?telecom=<ANI>&birthdate=<DOB>` with 6 phone format probes.
  Fails when patient's record doesn't have the caller's phone number.
  Fix in Session 0013: `fhir_query` tool with `family+given+birthdate`
  search capability.

- **The `anthropic_version` for Bedrock is `bedrock-2023-05-31`** — NOT
  `bedrock-2023-10-16`. This was wrong initially and fixed.

- **CDK `cdk deploy` with escalation queue requires context variable:**
  ```
  npx cdk deploy pf-voice-qa-connect -c env=qa \
    -c "escalationQueueArn=arn:aws:connect:us-east-1:086514900943:instance/bc48ce14-1766-44c9-807b-4807e6010dd6/queue/56d2736b-5e63-454f-b01b-52591e650a55"
  ```
