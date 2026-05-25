# Session 0011 — Lex + Nova 2 Sonic + Connect rewrite + architecture correction

**Date:** 2026-05-24
**Goal:** Implement the ADR-0018 corrected architecture, write user
journeys, then correct the design again when evaluation revealed we'd
built an IVR instead of an AI agent. Final architecture: ADR-0019
(LLM-powered code-hook) + ADR-0020 (pf_org_uuid as practice key).

## What was done

### Pre-code deliverables (Session 0010 mandate: no code before these)

- **JTBD architecture doc** (`docs/architecture-jtbd.md`): maps four
  caller jobs-to-be-done (verify identity, lab status, visit summary,
  document status) to practice-quantifiable metrics, minimum AI
  behaviors, and tool surfaces. Architecture works back from JTBDs,
  not forward from AWS primitives.
- **Primary-source research doc** (`docs/research/lex-nova-sonic-research.md`):
  every CFN property, action type, and API name verified against
  primary-source docs with URLs. Key findings:
  - Nova Sonic is configured via `BotLocale.UnifiedSpeechSettings.SpeechFoundationModel`
  - Nova Sonic v1 is legacy (EOL Sep 2026); using Nova 2 Sonic instead
  - Connect flow action for Lex is `ConnectParticipantWithLexBot` (not `GetCustomerInput`)
  - `Set voice` block (`UpdateContactTextToSpeechVoice`) is Polly-only, not needed for Nova Sonic
  - Discovered `AMAZON.BedrockAgentIntent` as alternative path (documented, not chosen for v1)
  - Lambda code-hook configured on BotAlias, not Bot
  - `InvokeLambdaFunction` has 8s max timeout (fine for router)

### Implementation

- **Router Lambda** (`tools/router_lookup/`): reads phone_routing DDB
  by DID, returns `{practice_id}` as STRING_MAP for Connect. 4 tests.
- **Lex stack** (`infra/lib/lex-stack.ts`): Lex V2 bot with Nova 2
  Sonic at en_US locale, VerifyAndResolve intent (3 required slots:
  CallerFirstName, CallerLastName, DateOfBirth), FallbackIntent,
  code-hook Lambda on BotAlias. 9 jest tests.
- **Code-hook Lambda** (`tools/lex_code_hook/`): Lex V2 dialog/fulfillment
  handler skeleton. DialogCodeHook delegates to Lex; FulfillmentCodeHook
  acknowledges slots collected (stub — Session 0012 wires to
  lookup_patient via Gateway). 7 tests.
- **Connect stack rewrite** (`infra/lib/connect-stack.ts`): completely
  rewritten. All ADR-0011 dead code removed (no AwsCustomResource, no
  AI agent role, no InvokeAWSService, no InvokeAIAgent). Flow now:
  InvokeLambdaFunction (router) → UpdateContactAttributes (practice_id) →
  ConnectParticipantWithLexBot (Lex + Nova Sonic) → DisconnectParticipant.
  8 jest tests including negative assertion that no non-existent actions
  are used.
- **Updated `app.ts`**: LexStack wired between AgentGateway and Connect;
  ConnectStack takes `lexBotAliasArn` prop instead of `agentCoreGatewayArn`.
- **Docs updated**: `architecture.md` (full rewrite), `context.md`
  (decisions table corrected), `CLAUDE.md` (flow diagram corrected).

### Test results

- **153 Python tests**: all passing (agent: 3, lookup_patient: 53,
  complete_verification: 1, escalate_to_human: 1, router_lookup: 4,
  lex_code_hook: 7, audit: 10, oauth: 53, routing: 14, api: 6, ci: 1)
- **43 CDK jest tests**: all passing (connect: 8, lex: 9, agent-gateway: 5,
  api: 14, phone-routing: 3, infra: 4)
- **`make test-ci-unit`: GREEN**

## Decisions made

- **Nova 2 Sonic over Nova Sonic v1:** v1 is legacy with EOL Sep 2026;
  model ARN `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-sonic-v1:0`.
  No ADR needed — straightforward model version choice.
- **Single VerifyAndResolve intent:** one intent covers the entire
  conversation (verification + any post-verification JTBD). The
  code-hook Lambda manages the state machine, not Lex's intent
  classification. Avoids intent-per-JTBD rigidity.
- **Path A (code-hook) over Path B (BedrockAgentIntent):** Path B is
  documented in `architecture-jtbd.md` but not chosen because Nova Sonic
  + BedrockAgentIntent compatibility is unverified. Code-hook path is
  the safer bet.

## Open questions

1. **Code-hook → lookup_patient wiring (Session 0012).** The fulfillment
   handler is a stub. Session 0012 needs to call `lookup_patient` via
   AgentCore Gateway and handle the verification result.
2. **Lex slot/intent rigidity.** ADR-0018's kill criterion: if Lex's
   slot model can't handle the disambiguation step (two or more
   candidates), revisit Path B (BedrockAgentIntent) or KVS streaming.
3. **Deploy of Connect + Lex stacks.** CDK synth is clean. Actual deploy
   needs the Connect instance (already exists from Session 0010) and
   will create the Lex bot + router Lambda. Deploy should be attempted
   in Session 0012.
4. **`UpdateContactAttributes` Parameter format.** The flow uses
   `$.External.practice_id` to reference the router Lambda response.
   This needs validation at deploy time — Connect's expression syntax
   may differ from what's documented.

## Next session pickup

**Read these files first, in this order:**

1. `docs/sessions/forward-plan-revised.md` — the JTBD-aligned session plan
2. `docs/decisions/0019-llm-powered-code-hook.md` — WHY Claude is in the loop
3. `docs/decisions/0020-pf-org-uuid-as-practice-key.md` — WHY we use PF's GUID
4. `docs/user-journeys.md` Part 8 (gap analysis) — WHAT's missing
5. `docs/research/lex-nova-sonic-research.md` — verified CFN/API surfaces

**Session 0012 goal:** "I can call the number and have a real AI
conversation that verifies me." Mohit dials a DID, Claude drives a
natural conversation, lookup_patient fires, "I've verified you, Mohit."
Under 30 seconds.

**What Session 0012 must build:**

1. **Rewrite code-hook Lambda** — replace rigid slot logic with:
   - FallbackIntent fulfillmentCodeHook (not dialogCodeHook)
   - Call Bedrock InvokeModel (Claude Sonnet) every turn
   - System prompt = `agent/prompts/verification.md`
   - Conversation history in session attributes
   - Tool execution: call lookup_patient directly on Claude's request
   - Return ElicitIntent + Claude's text (loop) or Close (done)

2. **Rewrite Lex bot** — strip the 3 required slots and VerifyAndResolve
   intent. Replace with single FallbackIntent + fulfillmentCodeHook.
   Keep Nova 2 Sonic UnifiedSpeechSettings.

3. **Rename practice_id → pf_org_uuid** everywhere:
   - All Python code (handler.py, stores, tests)
   - All CDK stacks (env vars, DDB key names, outputs)
   - Router Lambda, contact flow, session attributes
   - Use `b4ab304f-d1ac-4565-8dca-992b589422a7` for the pilot

4. **Create PracticesStack** — DDB tables for practices, oauth-tokens,
   oauth-state. KMS `oauth-key` CMK. Wire cross-stack refs.

5. **Fix env var names** — reconcile CDK names with Lambda code names.

6. **Fix contact flow** — UNKNOWN-DID branch, post-Lex queue routing.
   Create two Connect queues.

7. **Deploy all stacks** and seed the pilot practice data.

8. **Make the call.** Dial the DID from +17163619276. Verify as
   Mohit Durve, DOB 1991-06-09.

**Pass/fail for Session 0012:**
- PASS: Natural AI conversation, verification in <30s, says "Mohit" back.
- FAIL: Feels like a phone tree, or latency >30s, or verification wrong.

**First failing test for Session 0012:**
`tools/lex_code_hook/tests/test_handler.py::test_fulfillment_calls_bedrock_with_verification_prompt`
— asserts the code-hook calls `bedrock-runtime:InvokeModel` with the
verification prompt as system content and the inputTranscript in the
conversation history.

## Files changed

- `tools/router_lookup/` (new package) — router Lambda
- `tools/lex_code_hook/` (new package) — Lex code-hook Lambda
- `infra/lib/lex-stack.ts` (new) — Lex bot + Nova 2 Sonic + code-hook
- `infra/lib/connect-stack.ts` — full rewrite (ADR-0018)
- `infra/test/connect-stack.test.ts` — rewritten for ADR-0018
- `infra/test/lex-stack.test.ts` (new) — 9 tests
- `infra/bin/app.ts` — LexStack wired, ConnectStack props updated
- `Makefile` — `tools/router_lookup` and `tools/lex_code_hook` added to PYTHON_PKGS
- `docs/architecture.md` — full rewrite for ADR-0018
- `docs/architecture-jtbd.md` (new) — JTBD-first architecture mapping
- `docs/research/lex-nova-sonic-research.md` (new) — primary-source research
- `docs/user-journeys.md` (new) — 878-line user journey doc with personas, sequences, edge cases
- `docs/diagrams/architecture-high-level.svg` (new)
- `docs/diagrams/call-state-machine.svg` (new)
- `docs/diagrams/onboarding-flow.svg` (new)
- `docs/diagrams/phi-data-flow.svg` (new)
- `docs/sessions/0011-evaluation-and-forward-plan.md` (new) — gap analysis
- `docs/sessions/forward-plan-revised.md` (new) — JTBD-aligned session plan
- `docs/decisions/0019-llm-powered-code-hook.md` (new) — Claude in the loop
- `docs/decisions/0020-pf-org-uuid-as-practice-key.md` (new) — drop practice_id
- `docs/context.md` — decisions table corrected
- `CLAUDE.md` — architecture diagram + "NOT" list updated for ADR-0019/0020

## Notes for future Claude

- **`ConnectParticipantWithLexBot` is the flow-language type name for
  "Get customer input" (Lex target).** Previous sessions called it
  `GetCustomerInput` — that's the console label, not the JSON type.
- **Nova Sonic v1 (`amazon.nova-sonic-v1:0`) is legacy with EOL
  September 14, 2026.** Use Nova 2 Sonic (`amazon.nova-2-sonic-v1:0`).
  The architecture doc, CLAUDE.md, and CDK stacks all reference v2.
- **`UpdateContactTextToSpeechVoice` is Polly-only.** No Set voice
  block is needed for Nova Sonic — it's configured at the Lex bot
  locale level via `UnifiedSpeechSettings.SpeechFoundationModel`.
- **`AMAZON.BedrockAgentIntent` exists and is CFN-supported.** If the
  code-hook Lambda's dialog management becomes too rigid for the
  verification conversation, this is the escape hatch — it delegates
  the entire conversation to a Bedrock Agent. See
  `docs/architecture-jtbd.md` Path B.
- **The code-hook Lambda is a skeleton.** It delegates on dialog hooks
  and returns a stub message on fulfillment. Session 0012 must wire
  the actual `lookup_patient` call and verification logic.
- **CDK test for contact flow content:** the flow JSON contains Lambda
  ARN tokens (`Fn::Join`), so tests must match on the stringified
  representation, not parse the JSON as an object.
- **FallbackIntent uses fulfillmentCodeHook, not dialogCodeHook.**
  FallbackIntent has no slots, so there's no dialog phase — it goes
  straight to fulfillment. The code-hook `invocationSource` will be
  `"FulfillmentCodeHook"`, not `"DialogCodeHook"`. Verified from
  primary-source Lex V2 FallbackIntent docs.
- **ElicitIntent loop pattern:** code-hook returns `ElicitIntent` +
  messages → Lex speaks the message, listens → no intent matches →
  FallbackIntent fires again → code-hook fires again. This is the
  conversation loop. Confirmed by AWS Lex docs: "If your Lambda
  function uses the ElicitIntent dialog action..."
- **Session attribute size limit is 12KB.** Conversation history stored
  in session attributes must be compact. ~20 turns of text fits.
  Consider truncating older turns if the conversation runs long.
- **Lex session timeout is 15 minutes.** No per-turn limit. No loop
  detection. We manage our own turn counting if needed.
- **The Lex bot CDK (lex-stack.ts) needs rewriting in Session 0012.**
  Strip the VerifyAndResolve intent + 3 slots. Replace with a single
  FallbackIntent + fulfillmentCodeHook. The current code in lex-stack.ts
  is the rigid-slot version — it will be replaced.
- **Bedrock InvokeModel adds ~1-3s latency per turn.** This is the
  biggest UX risk. If too slow, try Claude Haiku or Nova Lite.
  Measure in Session 0012 before optimizing.
- **The pilot practice data for seeding:**
  - `pf_org_uuid`: `b4ab304f-d1ac-4565-8dca-992b589422a7`
  - `fhir_base_url`: `https://qa-api.practicefusion.com/fhir/r4/v1/b4ab304f-d1ac-4565-8dca-992b589422a7`
  - `client_id`: `52011f70-a8c4-4c75-822c-d38d081bbc53`
  - `client_secret_arn`: `arn:aws:secretsmanager:us-east-1:086514900943:secret:pf-voice-qa-pf-client-secret-nCNxiK`
  - Test patient: Mohit Durve, DOB 1991-06-09, phone (716) 361-9276
  - Test patient: Ayesha Durve, DOB 1991-06-09, phone (716) 491-6872
