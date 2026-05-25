# ADR-0006: Practice Fusion `Patient.telecom` search uses literal string matching — query in PF's storage format

**Status:** Accepted
**Date:** 2026-05-23 (Session 0002 empirical finding)

## Context

Our original plan (ADR-0001 + the verification flow in `docs/architecture.md`) assumed we could normalize caller phone input to E.164 (`+1XXXXXXXXXX`) and search `Patient?telecom=+15551234567&birthdate=YYYY-MM-DD` against Practice Fusion's FHIR R4 endpoint.

The Session 0002 spike characterized PF QA's actual `telecom` search behavior by:

1. Discovering two test patients (Mohit Milind Durve, Ayesha Durve) via name search.
2. Reading their stored `telecom` arrays: both have `phone` entries stored as `(NPA) NXX-XXXX` (e.g., `(716) 361-9276`).
3. Probing `Patient?telecom=...` with five format variants and recording which matched.

Result (identical across both test patients):

| Probe format | Match? |
|---|---|
| `(716) 361-9276` — literal stored format | ✓ |
| `(716) 361-9276` — re-built `(NPA) NXX-XXXX` | ✓ |
| `7163619276` — digits only | ✗ |
| `+17163619276` — E.164 | ✗ |
| `716-361-9276` — dashed | ✗ |

PF's `telecom` token-search appears to do **literal string comparison** against `Patient.telecom.value`, with no phone-number normalization. The format we query with **must equal** the format stored.

## Decision

The `lookup_patient` Lambda will:

1. **Normalize caller input to 10 raw digits** (strip everything non-digit, drop leading `1`).
2. **Format the query value as `(NPA) NXX-XXXX`** (PF's apparent default storage format) before issuing `Patient?telecom=`.
3. **If that single-format query returns zero matches, probe additional format variants** in priority order: `NNN-NNN-NNNN`, `NNN.NNN.NNNN`, `(NNN)NNN-NNNN`, `NNN NNN NNNN`, digits-only. Stop at the first match. This handles practices whose data-entry conventions differ from PF's UI default.
4. **Always combine with `birthdate=` as a secondary discriminator** — narrows multi-tenant collisions and reduces false positives if a `telecom` value happens to repeat across patients.

The `tools/lookup_patient/src/lookup_patient/normalize.py` helper continues to exist but will be **renamed in semantics**: `normalize_e164` was the wrong abstraction. Session 0003 introduces `to_pf_phone_formats(input) -> list[str]` that yields the priority-ordered list of probe formats from any common US input.

## Why this matters more broadly

This is a **PF-specific search semantic** that other SMART servers (Epic, Cerner, etc.) handle differently. The `lookup_patient` tool encapsulates this quirk — the agent above it sees only "match / no match / multiple match" and never has to know about phone formatting. Keep the quirk in one place.

## Consequences

**Positive:**
- We can verify patients with realistic confidence on PF QA today, with formats practices actually use.
- The fix lives in one Lambda; the agent and tool interface stays clean.

**Negative:**
- A multi-format probe means up to N HTTP calls per verification, increasing latency. Phase 1 budget allows for this; if it becomes a hotspot we cache the per-practice "winning format" in DynamoDB to short-circuit later calls.
- A practice with truly inconsistent phone storage (some `(NPA) NXX-XXXX`, some digits) could miss matches in v1. Acceptable for the pilot; revisit if we see verification failures clustering by practice.

**Operational follow-ups:**
- Add the "stored telecom format" probe to the per-practice onboarding diagnostics — sample the first 10 Patient records, infer the format histogram, store as a hint.
- Audit-log every probe-set per call so we can build a real format-prevalence dataset from production traffic.

## Validation criteria

Session 0003 ships with unit tests that exercise the multi-format probe behavior against recorded fixtures plus a `@pytest.mark.integration` test that successfully retrieves both Durve test patients via the verification-style lookup using only their natural-language phone input (e.g., `"716 361 9276"`, `"7163619276"`).
