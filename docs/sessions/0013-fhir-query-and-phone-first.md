# Session 0013 — FHIR Query Tool, Phone-First Verification, Agent Polish

**Date:** 2026-05-24 to 2026-05-25
**Goal:** "I call, verify, ask about my labs, and get an answer."

## What was done

### Phase A: Build (TDD)

1. **`fhir_query` package** — new tool with 12 FHIR resource projections
   (AllergyIntolerance, CarePlan, CareTeam, Condition, DiagnosticReport,
   DocumentReference, Encounter, Goal, Immunization, MedicationRequest,
   Observation, Procedure). Voice-safe field extraction strips clinical
   values. PF's overloaded `code.text` handled (prefer `coding.display`).

2. **Shared credential resolver** — extracted `_get_credentials()` from
   lookup_patient to `oauth/credentials.py`. Both tools import from one place.

3. **lookup_patient name fallback** — `family+given+birthdate` search when
   all phone probes return zero. Fixes patients without caller's phone on file.

4. **Code-hook handler** — added `complete_verification` + `fhir_query` tools,
   conversation phase tracking (`verification` → `service`), `Close(Fulfilled)`
   on graceful goodbye, `_MAX_TOOL_ROUNDS` raised to 5.

5. **Two-phase prompt** (`patient_service.md`) — verification → service with
   12 resource types, patient-friendly language, acknowledgment enforcement.

### Phase B: Critical Bugs Found and Fixed

1. **Conversation history corruption** — handler saved text-only history
   pairs, but tool_use/tool_result blocks were lost. Next turn sent
   orphaned tool_use references to Claude → Bedrock rejected with
   `ValidationException`. Fixed: save full `messages` array including
   tool interactions. Added `_sanitize_history()` and safe truncation
   that never breaks tool_use/tool_result pairs.

2. **PF code.text overloading** — PF stuffs metadata into `code.text`
   ("Nicotine dependence; 2026-03-11; active; Dr Killian; ..."). Fixed:
   prefer `coding[0].display`, filter out semicolon-containing text.

3. **Phone probe format gap** — Mohit's phone stored as `+1(716)361-9276`
   but probe formats didn't include `+1(NPA)NXX-XXXX`. Added to
   `to_pf_phone_formats()` along with E.164 `+1XXXXXXXXXX`. Now 8 formats.

### Phase C: Phone-First Verification

1. **Proactive phone probe** — on first turn, handler searches Patient by
   ANI before calling Claude. Result injected into system prompt context.

2. **Contact flow greeting** — changed from "Hello, thank you for calling.
   How can I help you today?" to "One moment while I look up your account."
   Covers probe latency, eliminates double greeting.

3. **Prompt scenarios** — A (single match → "Is this Mohit?" → DOB → 2 turns),
   B (multiple → ask name → 3 turns), C (none → standard flow → 4 turns).

4. **phone_match flag** — lookup_patient also runs phone-only search; if
   ANI matches the found patient, sets `phone_match: true` → Claude skips
   phone last-four confirmation.

### Live Call Results

- Phone probe found Mohit → "Is this Mohit?" → DOB confirmed → verified in 2 turns ✓
- Asked about conditions → got clean names (Nicotine dependence, Essential hypertension, Heart failure) ✓
- "Let me check on that" acknowledgments before tool calls ✓
- No double greeting ✓
- Service phase survived multiple questions without history corruption ✓

## Decisions made

- **Strands/AgentCore deferred to v2.** Current code-hook + InvokeModel is
  simpler, faster, and Lex doesn't support streaming anyway. Strands becomes
  valuable when we add web chat as a second channel — the tools are already
  cleanly separated for porting.
- **12 FHIR resource types** based on PF OAuth scope (17 resources) minus
  reference-only ones. ServiceRequest/Coverage/MedicationDispense are 403
  (not in scope).
- **PF literal-telecom requires 8 probe formats** including `+1(NPA)NXX-XXXX`
  and E.164. Any time PF stores phones differently, add the format here.

## CDK debt (from this session)

| Resource | In CDK? | Fix needed |
|---|---|---|
| Contact flow `Text` = "One moment while I look up your account" | NO (CLI) | Update connect-stack.ts |
| Code-hook Lambda code (new tools, history fix, phone probe) | NO (CLI) | CDK deploys from source — will pick up |
| `tools/fhir_query` in Lambda bundle | NO | Add to lex-stack.ts `pythonLambdaCode` |
| Phone format probes (8 not 6) | Code change | CDK deploys from source — will pick up |

## Test results

- **234 Python unit tests:** all passing across 12 packages
- **57 CDK jest tests:** all passing
- **6 integration tests:** skipped (need PF_* env vars)
- **Live call tests:** verification + conditions query + clean disconnect ✓

## Open questions

1. **ServiceRequest (lab orders) is 403.** Need to request `user/ServiceRequest.read`
   scope during OAuth onboarding, or lab orders surface differently in PF.
2. **Integration tests need PF env vars.** Should set up CI to run these
   against PF QA on every PR.
3. **Proactive probe adds ~2s to first turn.** Acceptable with "One moment"
   cover, but worth optimizing (cache, warm Lambda).

## Next session pickup

**Read these files first:**
1. `docs/sessions/0013-fhir-query-and-phone-first.md` — this file
2. `docs/sessions/0012-llm-code-hook-and-practices-stack.md` — prior session
3. `tools/lex_code_hook/src/lex_code_hook/handler.py` — the agent brain
4. `tools/fhir_query/src/fhir_query/handler.py` — FHIR query tool
5. `infra/lib/lex-stack.ts` — needs fhir_query added to bundle

**Session 0014 goal:** CDK deploy, prompt hardening, practice onboarding UI + dashboard.

### Session 0014 pickup prompt

Read these files in order:

1. `docs/sessions/0013-fhir-query-and-phone-first.md` — this file (what was built, what's deployed)
2. `docs/sessions/forward-plan-session-0014.md` — full JTBD analysis, onboarding UX design, dashboard wireframes
3. `docs/context.md` — business context
4. `docs/architecture.md` — system architecture
5. `CLAUDE.md` — project conventions (TDD, HIPAA, IaC, session logs)

Then do these in order:

**Step 0: CDK deploy (gate for everything else)**
```bash
npx cdk diff -c env=qa  # should show: Lambda code hash change + flow content
npx cdk deploy -c env=qa \
  -c "escalationQueueArn=arn:aws:connect:us-east-1:086514900943:instance/bc48ce14-1766-44c9-807b-4807e6010dd6/queue/56d2736b-5e63-454f-b01b-52591e650a55"
```
After deploy, re-run the Connect associations (CDK doesn't manage these):
```bash
aws connect associate-bot --instance-id bc48ce14-1766-44c9-807b-4807e6010dd6 --lex-v2-bot AliasArn=<BotAliasArn from CDK output>
aws connect associate-lambda-function --instance-id bc48ce14-1766-44c9-807b-4807e6010dd6 --function-arn <CodeHookLambdaArn from CDK output>
```
Then call +1 (615) 625-0631 to verify. If it works, proceed. If not, fix before doing anything else.

**Step 1: Prompt hardening** (before real patients see this)
- Emergency: "If this is a medical emergency, hang up and dial 911" — FIRST check every turn
- After-hours: practice config with business hours, polite close outside hours
- Non-English: detect and escalate gracefully
- Minors: verify caller is guardian on file

**Step 2: Practice onboarding UI** (the big build)
- Read `docs/sessions/forward-plan-session-0014.md` for the 5-step flow design
- React wizard in `web/` — paste FHIR URL → authorize → get DID → test call → go live
- The existing OAuth API (`api/src/api/routes.py`) handles /oauth/start and /oauth/callback — extend it with DID claiming
- Write ADR-0022 for dashboard auth approach before building

**Step 3: Dashboard MVP** (call log + transcripts)
- Call log: Connect contact search API or DynamoDB event log
- Transcript viewer: Lex conversation logs or our session history
- Kill switch: pause routing for a practice

**What's currently deployed and working:**
- Phone-first verification: "Is this Mohit?" → DOB → verified in 2 turns
- 12 FHIR resource queries with voice-safe projections
- Conditions query returns clean names (Nicotine dependence, Hypertension, Heart failure)
- "One moment while I look up your account" greeting → no double-hi
- Acknowledgments before tool calls
- History fix: tool_use/tool_result pairs preserved across turns

**Key constraints:**
- Work back from practice JTBDs (see forward plan), not forward from AWS capabilities
- Frictionless onboarding — Marty Cagan discovery principles
- ServiceRequest is 403 (not in OAuth scope) — need scope expansion for lab orders
- 6 integration tests need PF_* env vars — don't silently skip them
- Test every change with a real phone call before declaring it done
- CLI deploy first, CDK reconciliation last

**Pilot practice data:**
- `pf_org_uuid`: `b4ab304f-d1ac-4565-8dca-992b589422a7`
- Phone: `+16156250631` (Nashville DID)
- Connect instance: `bc48ce14-1766-44c9-807b-4807e6010dd6`
- Contact flow: `7d44dd04-a8dc-4059-95dd-51bb471be059`
- Lex bot: `Q8KEE7VWFQ` / alias `HI8OESGPSF` (version 3)
- Escalation queue: `56d2736b-5e63-454f-b01b-52591e650a55`
- Test patient Mohit Durve: `b79082d9-548c-454e-9fc7-ce19ab630776` (5 conditions, 7 encounters, phone `+1(716)361-9276`)

## Files changed

- `tools/fhir_query/` (new package) — handler, fhir_client, projections, 57 tests
- `oauth/src/oauth/credentials.py` (new) — shared credential resolver, 7 tests
- `tools/lookup_patient/src/lookup_patient/handler.py` — use shared credentials, phone_match
- `tools/lookup_patient/src/lookup_patient/fhir_client.py` — name fallback, phone-only search
- `tools/lookup_patient/src/lookup_patient/normalize.py` — 8 phone formats (was 6)
- `tools/lex_code_hook/src/lex_code_hook/handler.py` — history fix, phone probe, phase tracking, new tools
- `tools/lex_code_hook/src/lex_code_hook/prompts/patient_service.md` (new) — v6.0 two-phase prompt
- `Makefile` — added fhir_query to PYTHON_PKGS
- `tools/fhir_query/pyproject.toml` (new)
- Contact flow content updated via CLI (greeting text)
