# Revised Forward Plan — JTBD-Aligned, Measurable Sessions

**Date:** 2026-05-24 (end of Session 0011)

**Principles:**
1. Every session ends with something a person can experience (call, click, hear)
2. Every session has a measurable pass/fail criteria — not "tests pass" but "the thing works"
3. No session is purely infrastructure — infra ships alongside the feature it enables
4. The practice's org UUID (`pf_org_uuid`) is the identity key everywhere

---

## Session 0012: "I can call the number and have a real AI conversation that verifies me"

**JTBD served:** Caller identity verification (the gate for everything)

**Measurable outcome:** You (Mohit) dial a real phone number from your
cell phone (+17163619276). An AI agent powered by Claude has a natural
conversation with you, asks your name and DOB, calls PF FHIR, and says
"I've verified your identity, Mohit." End to end. Under 30 seconds.

**What gets built:**

1. **LLM-powered code-hook** — rewrites the skeleton to call Bedrock
   InvokeModel (Claude Sonnet) with the verification prompt +
   conversation history. Uses `ElicitIntent` loop pattern: every turn
   goes through the LLM, not rigid slots.

2. **Lex bot simplified** — strip the 3 required slots. One FallbackIntent
   with dialog code-hook. Nova 2 Sonic for speech. The LLM drives the
   conversation.

3. **Missing infrastructure** — practices table, oauth-tokens table,
   KMS CMK, all in one `PracticesStack`. Wire env vars. Fix naming.

4. **Contact flow fixed** — UNKNOWN-DID branch, post-Lex queue routing.
   Two Connect queues (verified, escalation).

5. **Deploy all stacks** — all 7-8 stacks to QA.

6. **Seed pilot practice** — write the `pf_org_uuid=b4ab304f-...` rows
   using data from the token response. Claim a DID.

7. **One real call** — dial the DID, verify as Mohit Durve, hear
   "I've verified your identity."

**Pass/fail:**
- PASS: Mohit dials, AI has a natural conversation (not robotic slot
  prompts), verifies identity in <30s, says his name back.
- FAIL: Conversation feels like a phone tree, or verification doesn't
  work, or latency is >30s.

**Kill criteria:**
- If Claude latency makes the conversation feel laggy (>3s between
  turns), measure and document. Consider Nova Pro or Haiku for lower
  latency.
- If Nova 2 Sonic speech quality is poor (accent issues, misrecognition),
  document and plan mitigation.

---

## Session 0013: "When the AI can't verify me, I get a human — fast"

**JTBD served:** Graceful escalation (no caller should ever be stuck)

**Measurable outcome:** Three test calls with three outcomes:
1. Call from Mohit's phone → verified → transferred to verified queue
2. Call from unknown phone → "I couldn't match" → transferred to
   escalation queue with context
3. Caller says "talk to a person" → immediately transferred

Each transfer lands in a Connect queue with contact attributes
(verification outcome, reason, practice info) visible to the agent.

**What gets built:**
1. All edge cases from user-journeys.md wired into the code-hook LLM flow
2. Multiple-match disambiguation (Ayesha and Mohit share DOB)
3. Rate-limit and credentials-expired handling
4. After-hours branching in contact flow
5. Connect queue configuration with contact attribute display

**Pass/fail:**
- PASS: All three test calls route correctly. Human agent sees context.
- FAIL: Any call gets stuck, dropped, or transferred without context.

---

## Session 0014: "I called about my labs and got an answer without talking to a human"

**JTBD served:** Lab/imaging result status (top inbound call driver)

**Prerequisite:** 30-min spike against PF QA to confirm DiagnosticReport
resources exist for the Durve test patients. If not, seed test data.

**Measurable outcome:** Mohit calls, verifies, says "are my lab results
back?", and hears: "Your labs from [date] are complete. Dr. [name] has
reviewed them." Call resolved. No human needed.

**What gets built:**
1. `lab_result_status` Lambda (FHIR DiagnosticReport query)
2. Tool integration in the code-hook LLM flow
3. Voice-readback rules (one item, offer more)
4. Audit logging for DiagnosticReport reads

**Pass/fail:**
- PASS: Call resolved with accurate lab status in <45 seconds total.
- FAIL: Wrong status, missing data, or caller has to repeat themselves.

---

## Session 0015: "I called about my visit notes and referral — both answered"

**JTBD served:** Visit summary + document/referral status

**Prerequisite:** 30-min spike each for CarePlan and DocumentReference
against PF QA.

**Measurable outcome:** Two test calls:
1. "What did the doctor say at my last visit?" → brief care-plan summary
2. "Did you send my referral letter?" → status + date

**What gets built:**
1. `visit_summary` Lambda (Encounter + CarePlan query)
2. `document_status` Lambda (DocumentReference query)
3. Both integrated into the LLM conversation flow

**Pass/fail:**
- PASS: Both calls answered accurately without human.
- FAIL: Data quality too poor to give useful answers (document this as
  a v1 scope reduction, not a failure — honest is better than wrong).

---

## Session 0016: "Maria can see what happened with every call today"

**JTBD served:** Practice visibility into call outcomes

**Measurable outcome:** Maria (you) opens a dashboard in the browser,
sees today's calls with outcomes (verified, resolved, escalated), and
can tell which calls the AI handled vs. which went to humans. No PHI
visible — just outcomes and masked phone numbers.

**What gets built:**
1. Cognito user pool + sign-in
2. Calls API (`GET /calls?practice_id=...`) reading from DDB
3. React dashboard with call list
4. Practice status page (connection health, token status)

**Pass/fail:**
- PASS: Dashboard loads, shows real call data from Sessions 0012-0015.
- FAIL: Dashboard doesn't show accurate data from actual calls.

---

## Session 0017: "The pilot practice is live and we'll know if anything breaks"

**JTBD served:** Operational readiness for one real practice

**Measurable outcome:** A real practice (or your QA practice standing in
for one) is onboarded, calls are flowing, and there are alarms that fire
if anything breaks.

**What gets built:**
1. CloudWatch alarms (token refresh failure, error rate, rate-limit hits)
2. CloudWatch dashboard (call volume, verification rate, latency p95)
3. Call recording + transcript capture in Connect
4. Practice onboarding runbook (tested by doing it)
5. Pilot go/no-go checklist (all rows green)

**Pass/fail:**
- PASS: Alarms fire correctly when you simulate a failure. Dashboard
  shows accurate metrics. Onboarding runbook works end-to-end.
- FAIL: Blind spots in monitoring, or onboarding has manual steps
  that aren't documented.

---

## What Changed From the Previous Plan

| Before (Session 0011 plan) | After (this plan) | Why |
|---|---|---|
| Code-hook has rigid Lex slots | Code-hook calls Claude for every turn | Building an AI agent, not an IVR |
| Invented `practice_id` | Use `pf_org_uuid` from token response | One fewer concept; PF's GUID is the identity |
| 6 sessions to pilot | 6 sessions to pilot (same count) | But each session now has a human-testable outcome |
| Session 0012 = "wire + deploy" | Session 0012 = "I can call and verify" | Measurable from the caller's perspective |
| Disambiguation = separate session | Disambiguation = Session 0013 (escalation) | Grouped by JTBD: "what happens when it fails" |
| Dashboard = Session 0016 (unchanged) | Dashboard = Session 0016 | Still the right sequence |
