# Session 0015 — Bedrock Agent POC and Connect AI Agents pivot

**Date:** 2026-05-25
**Goal (one sentence):** Test whether a Bedrock Agent with BedrockAgentIntent can replace the custom code-hook for voice calls.

## What was done

### Bedrock Agent POC (failed — torn down)
- Created Bedrock Agent `HT7DBZ3FOT` (Claude Sonnet 4.6) with two action groups: `search_patient` and `get_patient_records`
- Deployed two self-contained FHIR Lambdas (`pf-voice-poc-search-patient`, `pf-voice-poc-get-patient-records`) — both tested successfully via direct invoke
- Text-only test passed end-to-end: phone probe → "Hi, is this Mohit?" → DOB verify → "I see 5 active conditions" → records query
- Created Lex bot with `AMAZON.BedrockAgentIntent` — **failed on voice** because BedrockAgentIntent is turn-based (requires caller speech before activating)
- `LexInitializationData.InitialMessage` is **chat-only** — confirmed in AWS API docs, voice channel not supported
- Attempted workarounds (code-hook bridge, catch-all intent, generative AI settings) — all defeated the purpose of the POC
- **All POC resources destroyed**: Bedrock Agent, Lex bot, 3 Lambdas, contact flow, DID +16198804979, IAM roles, phone_routing row
- Production system on +16156250631 verified intact

### Connect AI Agents discovery
- Researched Connect AI Agents (`qconnect` service) as alternative
- Created assistant `954ffc94-ec76-477e-9a2e-77ab81e054b8` and associated with Connect instance
- Verified `qconnect` CLI: `create-assistant`, `create-ai-agent`, `create-ai-prompt` all work
- ORCHESTRATION agent type supports MCP tool configurations, custom prompts, guardrails, Connect instance binding
- Default agents auto-provisioned for all types (ORCHESTRATION, SELF_SERVICE, etc.)

### Call analysis for +18168590066
- 2 calls from this number: one escalated for `language_barrier` (2 turns), one caller hung up mid-verification (46s)
- Downloaded call recordings to ~/Downloads/
- Identified logging gap: no conversation transcripts persisted (no Bedrock invocation logging, no Lex conversation logs, no Contact Lens transcripts)

## Decisions made
- BedrockAgentIntent is not viable for agent-first voice UX (no ADR — POC finding, not architecture change)
- Connect AI Agents (qconnect ORCHESTRATION type) is the next path to evaluate
- POC code (poc/search_patient, poc/get_patient_records) is reusable — same FHIR logic, just needs MCP-compatible wrapper

## Open questions
1. Does AMAZON.QinConnectIntent support voice, or is it chat-only like LexInitializationData?
2. Can the ORCHESTRATION agent speak first on voice (agent-first greeting)?
3. How do MCP tools get registered? AgentCore Gateway? Flow modules? Inline config?
4. How do contact attributes (caller_phone, pf_org_uuid) reach the orchestration agent?
5. What does a customer-facing voice orchestration prompt look like? (default is agent-assist)
6. Does ElevenLabs TTS work with QinConnectIntent-based bots or only with flow-level prompts?

## Next session pickup

**The first thing the next session should do:**
1. Read this file.
2. Then read: `poc/README.md` (still has FHIR Lambda code reference), `poc/agent-instructions.md` (verification prompt to adapt)
3. Run: `aws qconnect get-ai-agent --assistant-id 954ffc94-ec76-477e-9a2e-77ab81e054b8 --ai-agent-id 66a1efe5-67b0-4b63-b415-9f9ae8f09291` to see the default orchestration agent
4. Goal for next session: **Build and test the Connect AI Agents POC end-to-end on a new DID**
5. Exit criteria: A live phone call to a new DID reaches the Connect AI Agent, the agent proactively looks up the caller by phone, verifies identity, and answers a records query — all without a custom code-hook Lambda.

**Execution order:**
1. Research the 6 open questions above from primary-source AWS docs (fetch the actual pages, don't guess)
2. Enable Bedrock model invocation logging (close the logging gap)
3. Redeploy FHIR Lambdas and register as MCP tools
4. Create custom orchestration prompt
5. Create ORCHESTRATION AI agent with tools
6. Set up ElevenLabs TTS (Secrets Manager + Set Voice block)
7. Build contact flow with QinConnectIntent bot, claim DID, add phone_routing row
8. End-to-end test + comparison with +16156250631

**Key resources:**
- Assistant: `954ffc94-ec76-477e-9a2e-77ab81e054b8`
- Connect instance: `bc48ce14-1766-44c9-807b-4807e6010dd6`
- Production DID (DO NOT TOUCH): `+16156250631`
- Production Lex bot: `Q8KEE7VWFQ` / alias `HI8OESGPSF`
- Test practice: `pf_org_uuid: b4ab304f-d1ac-4565-8dca-992b589422a7`

## Files changed
- `poc/lex_code_hook/handler.py` (new, then deleted with POC teardown — code still in git)
- `poc/test_agent.py` (new — boto3 script for testing Bedrock Agent text invocation)
- `poc/README.md` (unchanged — FHIR Lambda code still valid for reuse)

## Notes for future Claude
- `AMAZON.BedrockAgentIntent` is strictly turn-based on voice. It CANNOT start a conversation proactively. The caller must speak first. This is a fundamental limitation, not a configuration issue. Don't try to work around it with code-hooks — that defeats the purpose.
- `LexInitializationData.InitialMessage` is CHAT-ONLY. The AWS API docs confirm voice channel is not supported. Don't assume it works on voice.
- The `qconnect` CLI uses the `wisdom` service namespace internally (ARNs show `arn:aws:wisdom:...`). The assistant was auto-populated with default AI agents for all types when created.
- The Bedrock Agent text-only flow (InvokeAgent API) works perfectly — phone probe, verification, records all pass. The problem was only the Lex voice delivery layer.
- The production code-hook Lambda does NOT log conversation content (transcripts or Claude responses). Only metadata. Bedrock model invocation logging is not enabled. This is a gap that should be fixed in the next session.
- Call recordings are WAV files in `s3://pf-voice-qa-audit/connect/pf-voice-qa-086514900943/CallRecordings/ivr/` — they're the only record of what was actually said on calls.
- The POC IAM role needed `Resource: "*"` for `bedrock:InvokeModel` because cross-region inference profiles (`us.anthropic.claude-sonnet-4-6`) don't match `arn:aws:bedrock:us-east-1::foundation-model/*`.
