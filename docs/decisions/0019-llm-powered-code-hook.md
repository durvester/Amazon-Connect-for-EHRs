# ADR-0019: LLM-powered code-hook replaces rigid slot collection

**Status:** Accepted

**Date:** 2026-05-24 (Session 0011 evaluation)

**Supersedes:** The Lex slot-based design from Session 0011's initial
`lex-stack.ts` (VerifyAndResolve intent with 3 required slots).

**Related:** ADR-0018 (Lex orchestrates — preserved; this refines how),
ADR-0013 (decision logic in prompt — now actually used)

## Context

Session 0011 implemented Lex with rigid slot collection: three required
slots (CallerFirstName, CallerLastName, DateOfBirth) elicited in
sequence, with a code-hook Lambda containing hardcoded if/else logic.
The verification prompt (`agent/prompts/verification.md`) was never
used. The result was an IVR, not an AI agent.

The user correctly identified that we had bypassed agentic AI entirely.
The whole value proposition — a natural conversation that verifies
identity and resolves the caller's question — requires LLM reasoning in
the loop.

Three paths were evaluated:

1. **AMAZON.BedrockAgentIntent** — GA in CFN, but its compatibility with
   Nova Sonic `UnifiedSpeechSettings` on the same Lex locale is
   undocumented. Zero AWS docs show the combination. Carries the same
   risk as Sessions 0007-0009 (building on an unverified combination).

2. **Connect AI Agent Designer ("agentic self-service")** — Connect's
   own framework for AI agents with MCP tools. This is what Sessions
   0007-0009 were reaching for, but the APIs weren't available then.
   Needs verification before commitment. Deferred.

3. **Code-hook Lambda that calls Claude via Bedrock InvokeModel** —
   uses only independently verified, GA services. The code-hook fires
   every turn via the FallbackIntent loop pattern, sends conversation
   history + verification prompt to Claude, gets back a reasoned
   response. All components verified from primary-source docs.

## Decision

**Path 3: LLM-powered code-hook.** The Lex bot has a single
FallbackIntent with fulfillmentCodeHook enabled. Every caller utterance
triggers the code-hook. The code-hook:

1. Reads `inputTranscript` (raw caller text) from the Lex event
2. Appends to conversation history (stored in Lex session attributes)
3. Calls Bedrock InvokeModel (Claude Sonnet) with:
   - System prompt: `agent/prompts/verification.md`
   - Conversation history
   - Tool definitions: lookup_patient (and future tools)
4. If Claude requests a tool call: executes it, feeds result back
5. Returns `ElicitIntent` + Claude's text response → Lex speaks it,
   listens for the next utterance → FallbackIntent fires again → loop
6. When done: returns `Close(Fulfilled)` or `Close(Failed)`

The Lex bot is reduced to: speech I/O (Nova 2 Sonic) + turn-taking
plumbing. Claude is the brain. The verification prompt is the policy.

## Verified from primary sources

| Component | Verification | Source |
|---|---|---|
| FallbackIntent + fulfillmentCodeHook | Confirmed: Lambda fires on FallbackIntent | Lex V2 built-in-intent-fallback.html |
| ElicitIntent loop | Confirmed: code-hook returns ElicitIntent → Lex re-listens → FallbackIntent fires again | Same doc: "If your Lambda function uses the ElicitIntent dialog action..." |
| inputTranscript | Confirmed: contains raw caller text for speech input | Lex V2 lambda-input-format.html |
| Session attributes | Confirmed: persist across turns, up to 12KB | Lex V2 session management docs |
| 15-minute session limit | Confirmed: not adjustable. No per-turn limit. | Lex V2 quotas |
| Bedrock InvokeModel | GA, well-trodden | Bedrock API reference |
| Nova 2 Sonic + UnifiedSpeechSettings | Confirmed: locale-level CFN config | CFN aws-properties-lex-bot-unifiedspeechsettings.html |

## Consequences

- **The verification prompt is finally used.** ADR-0013's "decision
  logic in prompt" is no longer theoretical — it's the system prompt
  Claude receives every turn.
- **Natural conversation.** Claude handles "I'm calling about my labs"
  naturally and drives verification, instead of rigid "first name? last
  name? DOB?"
- **Latency per turn increases.** Each turn now includes a Bedrock
  InvokeModel call (~1-3s for Claude Sonnet). Total conversation latency
  is higher than pure Lex slot elicitation. Mitigations: use Claude
  Haiku for lower latency if Sonnet is too slow; measure in Session 0012.
- **Session attribute size limit (12KB).** Conversation history must be
  compact. ~20 turns of text should fit comfortably.
- **The 3-slot lex-stack.ts from Session 0011 needs rewriting.** The
  VerifyAndResolve intent with required slots is replaced by a single
  FallbackIntent. Session 0012 does this.
- **AgentCore Gateway remains for external MCP consumers.** The code-hook
  calls lookup_patient directly (it bundles the package). The Gateway is
  still the catalog for future non-voice consumers.

## Kill criterion

If Claude's per-turn latency consistently exceeds 3 seconds (caller
perceives awkward silence), switch to Claude Haiku or Nova Lite. If
even the fastest model is too slow, revert to the slot-based approach
(the code still exists) and accept the IVR-like experience for v1.
