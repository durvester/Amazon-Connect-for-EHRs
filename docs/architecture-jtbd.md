# Architecture: Jobs-To-Be-Done First

**Date:** 2026-05-24 (Session 0011)
**Rule:** Per `feedback_jtbd_drives_architecture.md`, every architectural
primitive must answer "which JTBD does this serve, and what business
metric does it move?" in one sentence.

---

## The Caller's Jobs-To-Be-Done

### JTBD 1: "Verify who I am so I can get help" (Gate)

| | |
|---|---|
| **Caller need** | Prove identity so the practice can discuss their record |
| **Practice metric** | Staff-minutes per verification attempt (target: 0 for automated calls) |
| **Secondary metric** | % of calls where caller hangs up waiting to verify (abandonment rate) |
| **Minimum AI behavior** | Collect name + DOB, match against PF Patient record, confirm exactly one match. If ambiguous, ask one disambiguating question (ZIP). If no match or >1 after disambiguation, route to human. |
| **Tool** | `lookup_patient` (exists, production-shaped) |
| **FHIR scope** | `user/Patient.read` |

This is the **gate** — nothing below runs until verification succeeds.
Automating this single step is the v1 value proposition. The three JTBDs
below are "resolve the call" extensions that keep the caller from needing
a human at all.

### JTBD 2: "Are my lab results back?" (Resolve)

| | |
|---|---|
| **Caller need** | Know whether results are ready and what happens next |
| **Practice metric** | % of lab-status calls fully resolved without human pickup |
| **Secondary metric** | Callbacks avoided per day (each callback = 2 staff-minutes) |
| **Minimum AI behavior** | After verification, query most recent DiagnosticReport. Read status + ordering provider name. Never read result values. "Your labs from 5/14 are complete — Dr. X has reviewed them, expect a call within 2 business days" or "Still pending, please call back after 5/30." |
| **Tool** | `lab_result_status` (not yet built) |
| **FHIR scope** | `user/DiagnosticReport.read` |

### JTBD 3: "What did the doctor tell me to do?" (Resolve)

| | |
|---|---|
| **Caller need** | Recall care instructions from a recent visit |
| **Practice metric** | % of "what did the doctor say" calls resolved without human |
| **Secondary metric** | Staff-minutes saved on post-visit follow-up calls |
| **Minimum AI behavior** | After verification, read most recent Encounter + active CarePlan. Summarize ≤3 care-plan bullets. "At your visit with Dr. X on 5/14, the plan was: [bullets]." |
| **Tool** | `visit_summary` (not yet built) |
| **FHIR scope** | `user/Encounter.read` + `user/CarePlan.read` |

### JTBD 4: "Did the doctor send my form/referral?" (Resolve)

| | |
|---|---|
| **Caller need** | Confirm a document was sent or find out when it will be |
| **Practice metric** | % of document-status calls resolved without human |
| **Secondary metric** | Front-desk interruptions avoided per day |
| **Minimum AI behavior** | After verification, query DocumentReference by category. "Yes, your school physical was sent to Lincoln Elementary on 5/20" or "Not yet — the doctor still needs to sign off." |
| **Tool** | `document_status` (not yet built) |
| **FHIR scope** | `user/DocumentReference.read` |

---

## From JTBDs to Architecture

### What the JTBDs demand from the voice surface

1. **Natural multi-turn dialog** — the caller doesn't say "I want to
   verify my identity"; they say "hi, I'm calling about my lab results."
   The AI must handle both the verification gate and the post-verification
   JTBD in one fluid conversation.

2. **Tool calling mid-conversation** — after collecting enough info, the
   AI calls a FHIR tool, reasons over the result, and speaks the answer.
   This happens 1-3 times per call (verification + one resolve tool).

3. **Strict PHI discipline** — no patient data is spoken before
   verification succeeds. After verification, only the minimum data
   needed to resolve the JTBD is spoken (status, dates, provider names
   — never raw clinical values).

4. **Graceful escalation** — if the AI can't resolve the call (ambiguous
   identity, missing data, out-of-scope request), it routes to a human
   with context attached.

### Mapping to AWS primitives

| JTBD requirement | AWS primitive | Why this one |
|---|---|---|
| Speech-to-speech voice | Nova Sonic on Lex bot locale | Verified via CFN `UnifiedSpeechSettings` |
| Multi-turn dialog + tool use | **Two viable paths — see below** | |
| FHIR tool execution | Lambda functions (existing) | Production-shaped, deployed |
| Per-practice routing | DID → phone_routing → practice_id | Deployed, working |
| Call routing/escalation | Connect contact flow | `InvokeLambdaFunction` + `ConnectParticipantWithLexBot` |

### The two viable paths for dialog + tool use

**Path A: Lex + Lambda Code-Hook (ADR-0018's design)**

```
Connect flow → Lex bot (Nova Sonic) → Lambda code-hook → AgentCore Gateway → FHIR Lambdas
```

- Lex defines intents/slots for the conversation structure
- Code-hook Lambda manages dialog state, calls tools via Gateway
- Verification prompt logic lives in the code-hook Lambda
- Pro: Well-trodden Connect + Lex + Lambda path; we control every step
- Con: We must define intents/slots upfront (rigid); we write the
  dialog-management code ourselves; ADR-0018's kill criterion explicitly
  flags this risk

**Path B: Lex + Bedrock Agent Intent (NEW — discovered in research)**

```
Connect flow → Lex bot (Nova Sonic) → AMAZON.BedrockAgentIntent → Bedrock Agent → Action Groups → FHIR Lambdas
```

- Lex handles speech (Nova Sonic) and hands off to a Bedrock Agent
- Bedrock Agent handles multi-turn dialog, reasoning, and tool calling
- Verification prompt becomes the Bedrock Agent's system prompt
- Action Groups call our existing FHIR Lambdas directly
- Pro: No custom dialog-management code; the agent handles intent
  classification, slot elicitation, disambiguation naturally; adding
  new tools = adding action groups
- Con: Less control over turn-taking; Bedrock Agent is newer (verify
  CFN support); latency profile unknown; AgentCore Gateway becomes
  unnecessary (the agent calls Lambdas directly via Action Groups)

**Recommendation:** Path B is architecturally cleaner for our JTBDs —
the caller's conversation is naturally fluid ("hi, calling about my
labs") and doesn't map cleanly to rigid Lex intents/slots. A Bedrock
Agent handles this natively. However, Path B has unverified open
questions (Nova Sonic + BedrockAgentIntent compatibility, CFN for
Bedrock Agent). **I recommend implementing Path A first (verified,
deployable today) with the code-hook Lambda designed so that a Path B
migration is a swap, not a rewrite.** If Path A's rigidity hits
ADR-0018's kill criterion during eval, Path B is the fallback.

---

## Session 0011 Scope

Given the JTBDs above, Session 0011 delivers:

1. **Router Lambda** — reads phone_routing, returns practice_id (JTBD
   prerequisite: multi-tenancy)
2. **Lex bot with Nova Sonic** — speech surface for all four JTBDs
3. **Rewritten Connect contact flow** — InvokeLambdaFunction (router) →
   ConnectParticipantWithLexBot (Lex + Nova Sonic)
4. **Intent structure** — one `VerifyAndResolve` intent that covers the
   natural conversation flow (verification + whichever JTBD the caller
   mentions); code-hook Lambda handles the state machine
5. **Code-hook Lambda skeleton** — receives Lex events, manages dialog
   state, calls `lookup_patient` through Gateway for verification

Tools for JTBDs 2-4 (`lab_result_status`, `visit_summary`,
`document_status`) are future sessions — the intent structure and
code-hook design must accommodate them without requiring an intent-per-JTBD
redesign.
