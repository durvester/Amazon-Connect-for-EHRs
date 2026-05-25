# ADR-0002: Amazon Nova Sonic for the voice pipeline (not Transcribe Medical + Polly)

**Status:** Accepted (to be validated in Session 9)
**Date:** 2026-05-22

## Context

The voice agent needs to convert caller audio to model input and model output back to spoken audio. Two paths:

1. **Pipeline:** Amazon Transcribe Medical (ASR) → Claude (text in / text out) → Amazon Polly Neural (TTS).
2. **Single model:** Amazon Nova Sonic — a speech-to-speech foundation model; audio in, audio out.

Latency matters: phone callers experience >800ms turn-around as awkward; >2s as "this is an IVR." A pipeline adds latency at each hop (ASR streaming endpoint, model inference, TTS synthesis) and forces transcript-stitching to handle partial utterances. A single speech-to-speech model collapses the pipeline.

## Decision

Default to **Amazon Nova Sonic** for the voice pipeline.

Fall back to the pipeline option if Session 9's latency measurement misses budget (<2.5s p95 per turn).

## Why

- Half the round-trip-time of the pipeline approach, based on AWS published numbers for Nova Sonic.
- One service instead of three — fewer failure modes, simpler IAM, simpler quotas.
- AgentCore Runtime supports Nova Sonic natively in its bidirectional streaming mode.

## Consequences

**Positive:**
- Lower latency → more natural conversation.
- Less code (no ASR/TTS plumbing to write).

**Negative:**
- We have no intermediate transcript by default; the audit trail must capture model-level events instead of clean text turns. Mitigation: AgentCore exposes structured turn events that we'll log to S3.
- Nova Sonic voice options are more limited than Polly's catalog. Acceptable for v1; revisit if practice branding demands custom voices.
- If Nova Sonic is unavailable in `us-east-1` at the time of Session 9, we have to either change region or fall back to the pipeline.

## Alternatives considered

- **AWS Polly + Bedrock + Transcribe Medical.** Rejected as default for latency reasons; kept as documented fallback.
- **ElevenLabs voice via API.** Rejected: introduces a non-AWS dependency outside the AWS BAA scope.
- **OpenAI Realtime API.** Rejected: not AWS-native; PHI flowing to a third party requires its own BAA.

## Validation criteria

In Session 9: measure p95 turn latency across 50 synthetic calls. If <2.5s, keep Nova Sonic. Otherwise pivot to the pipeline and update this ADR's status.
