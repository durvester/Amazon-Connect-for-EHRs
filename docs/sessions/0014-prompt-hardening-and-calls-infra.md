# Session 0014 — Prompt Hardening + Calls Infrastructure

**Date:** 2026-05-24
**Goal:** Safety-harden the agent prompt before real patients, fix API stack CDK conflict, lay calls table groundwork for dashboard.

## What was done

### Phase 0: CDK Deploy + API Stack Fix

1. **API stack table conflict resolved** — `api-stack.ts` was creating DDB tables (`practices`, `oauth-tokens`) that already existed in `PracticesStack`. Removed duplicate table/KMS key creation, now imports via props. This was a latent bug from Session 0008 (API stack) vs Session 0012 (PracticesStack) — both claimed the same table names.

2. **Deleted stuck stack** — `pf-voice-qa-api` was in `REVIEW_IN_PROGRESS` (changeset never executed due to the conflict). Deleted and redeployed fresh.

3. **All 8 stacks deployed** — code-hook Lambda hash updated (Session 0013 changes reconciled from CLI to CDK).

### Phase 1: Prompt Hardening (TDD)

4. **Emergency 911 detection** — new section at the TOP of `patient_service.md`. Claude scans every turn for emergency keywords (chest pain, can't breathe, suicidal, etc.) and redirects to 911 before any verification. Escalation reason: `emergency`.

5. **After-hours handling** — `business_hours_status` + `business_hours_display` injected into the system prompt context block. When `closed`, Claude delivers a polite close with office hours. `PracticeRecord` now has an optional `business_hours` field (JSON in DDB).

6. **Non-English escalation** — prompt instructs Claude to detect non-English speech and escalate with reason `language_barrier`.

7. **Sensitive diagnosis gating** — Claude will never read back conditions related to HIV/AIDS, STIs, substance abuse, psychiatric diagnoses, genetic conditions, or reproductive health. Redirects to patient portal.

8. **Minor/guardian awareness** — prompt instructs Claude to ask for guardian verification when caller is calling about a child. Escalates with reason `guardian_unverified` if phone doesn't match.

9. **New escalation reasons** — handler tool definition expanded: `emergency`, `language_barrier`, `guardian_unverified` added to enum.

### Phase 2: Calls Table Infrastructure

10. **Calls DynamoDB table** — new `calls-stack.ts`. PK: practice_id, SK: call_id. GSI: `by-started-at` for time-range queries. TTL (90 days). DynamoDB Streams enabled for future real-time dashboard.

11. **Call record on Close** — handler writes metadata (practice_id, call_id, outcome, turn count, caller_phone_masked, escalation_reason) to calls table on every Close (fulfilled, escalated, max_turns). No PHI.

12. **Escalation reason tracking** — when Claude calls `escalate_to_human`, the reason is stored in session_attrs and persisted in the call record.

## Decisions made

- **No ADR for calls table** — simple data store, follows existing DDB patterns. Schema: practice_id/call_id PK/SK, started_at GSI.
- **business_hours stored as JSON string in DDB S attribute** — simpler than DDB Map type, practices store deserializes on read. Optional field, defaults to None (always open).
- **Prompt hardening is prompt-only for most sections** — only after-hours required code changes (practices store + handler). Emergency, non-English, sensitive dx, and minors are prompt-only with escalation paths that already existed.
- **API stack tables moved to props** — PracticesStack owns practices + oauth-tokens tables; API stack receives them as imports. Eliminates cross-stack resource ownership conflict.

## CDK debt (from this session)

| Resource | In CDK? | Notes |
|---|---|---|
| Calls table | YES | New `calls-stack.ts` |
| Code-hook Lambda (prompt hardening + call record) | YES | CDK deploys from source |
| `business_hours` field on practices table | NO (schema-level) | DDB is schemaless; no CDK change needed |
| CALLS_TABLE_NAME env var on code-hook Lambda | YES | Wired in `lex-stack.ts` |

## Test results

- **249 Python unit tests:** all passing across 12 packages (was 234; added 14 new)
- **53 CDK jest tests:** all passing across 8 suites (was 49; added 4 new)
- **Live call tests:** verification + conditions query + disconnect ✓ (call record write had empty `started_at` bug — fixed and redeployed)

## Open questions

1. **After-hours hours not yet set for pilot practice.** Need to write `business_hours` to the practices table for `b4ab304f-d1ac-4565-8dca-992b589422a7` when the practice provides their hours.
2. **Guardian verification is prompt-only.** Full implementation needs RelatedPerson FHIR query — deferred to v2.
3. **Sensitive diagnosis filtering is prompt-only.** Could be enforced at the FHIR projection level for defense-in-depth — deferred.

## Next session pickup

**Read these files first:**
1. `poc/README.md` — POC status, deployed resources, next steps with exact CLI commands
2. `poc/agent-instructions.md` — Bedrock Agent system prompt
3. `poc/search_patient/handler.py` — deployed, tested live
4. `poc/get_patient_records/handler.py` — deployed, tested live
5. `docs/sessions/0014-prompt-hardening-and-calls-infra.md` — this file (what was built in the main system)

**Session 0015 goal:** Complete the Bedrock Agent POC (Chunks 5-7), then decide architecture direction.

### Session 0015 pickup prompt

**Phase A: Complete the POC (Chunks 5-7)**

The POC tests whether Bedrock Agent + ElevenLabs TTS can replace the current code-hook Lambda architecture. Two Lambdas are deployed and tested. Three IAM roles exist. The remaining work:

1. **Chunk 5: Create Bedrock Agent** — `poc/README.md` has exact CLI commands. Create agent with Claude Sonnet 4.6, two action groups (search_patient, get_patient_records), prepare + alias. Test via `invoke-agent` CLI (text-only, no voice). The agent prompt is at `poc/agent-instructions.md`.

2. **Chunk 6: Create Lex Bot** — Create bot with `AMAZON.BedrockAgentIntent` pointing to the agent. Enable generative AI features. Build locale. Test via Lex console text chat.

3. **Chunk 7: Connect Flow + ElevenLabs + DID** — Store ElevenLabs API key in Secrets Manager, create contact flow with `Set voice` (ElevenLabs) + router Lambda + Lex handoff, claim DID, add phone_routing row. Test with live call.

4. **Compare** — Call POC DID vs existing DID (`+16156250631`). Compare voice quality, latency, verification flow, FHIR queries.

**Phase B: Architecture Decision**

Based on POC results, write ADR-0025:
- If POC works: plan migration from code-hook to Bedrock Agent
- If POC fails: document why, keep code-hook, plan Strands-in-Lambda for multi-channel

**Phase C: Onboarding UI + Dashboard (if time)**

The forward plan at `docs/sessions/forward-plan-session-0014.md` has full JTBD analysis and onboarding UX design. This work is independent of the architecture POC.

**Deployed POC resources (all prefixed `pf-voice-poc-*`):**
- Lambda: `pf-voice-poc-search-patient` (tested, returns Mohit)
- Lambda: `pf-voice-poc-get-patient-records` (tested, returns 5 conditions)
- IAM: `pf-voice-poc-agent-role`, `pf-voice-poc-lambda-role`, `pf-voice-poc-lex-role`

**Existing system (DO NOT TOUCH):**
- `pf_org_uuid`: `b4ab304f-d1ac-4565-8dca-992b589422a7`
- Existing DID: `+16156250631` (Nashville)
- Connect instance: `bc48ce14-1766-44c9-807b-4807e6010dd6`
- Lex bot: `Q8KEE7VWFQ` / alias `HI8OESGPSF`

## Files changed

- `infra/lib/api-stack.ts` — removed duplicate table/key creation, tables via props
- `infra/lib/calls-stack.ts` (new) — calls DDB table
- `infra/lib/lex-stack.ts` — added callsTableName/Arn props, CALLS_TABLE_NAME env var, IAM grant
- `infra/bin/app.ts` — wired CallsStack, passed practices tables to ApiStack
- `infra/test/api-stack.test.ts` — updated for new ApiStackProps
- `infra/test/calls-stack.test.ts` (new) — 4 CDK tests
- `tools/lex_code_hook/src/lex_code_hook/handler.py` — business_hours context, new escalation reasons, call record write, escalation_reason tracking
- `tools/lex_code_hook/src/lex_code_hook/prompts/patient_service.md` — v7.0 prompt (emergency, after-hours, non-English, sensitive dx, minors)
- `tools/lex_code_hook/tests/test_handler.py` — 13 new tests (9 prompt hardening + 4 call record)
- `oauth/src/oauth/practices_store.py` — business_hours field on PracticeRecord
- `oauth/tests/test_practices_store.py` — 2 new tests for business_hours

## Notes for future Claude

- The API stack was in a broken state (REVIEW_IN_PROGRESS) because Session 0008 created tables that Session 0012 also created in PracticesStack. This session fixed it. If you see similar "already exists" errors, check for duplicate resource definitions across stacks.
- `business_hours` is stored as a JSON string in a DDB `S` attribute, not a DDB `M` (Map). The practices store deserializes it. This is intentional — keeps the DDB interface simple and avoids nested attribute marshalling.
- The `_write_call_record` function gracefully no-ops when `CALLS_TABLE_NAME` is not set (e.g., local testing). It logs a debug message and returns.
