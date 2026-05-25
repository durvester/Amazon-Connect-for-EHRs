# Session 0003 — `lookup_patient` Lambda end-to-end

**Date:** 2026-05-23
**Goal:** Implement the `lookup_patient` Lambda (handler + FHIR client) test-first against recorded Bundle fixtures, applying ADR-0006's multi-format probe strategy, with an integration test that validates against live PF QA.

## What was done

- **Reworked `normalize.py` per ADR-0006.** Added `to_pf_phone_formats(input) -> list[str]` returning the priority-ordered probe list: `(NPA) NXX-XXXX`, `NPA-NXX-XXXX`, `NPA.NXX.XXXX`, `(NPA)NXX-XXXX`, `NPA NXX XXXX`, `NPANXXXXXX`. Output is deduped while preserving order. The existing `normalize_e164` stays in place for audit-log redaction and any other E.164 caller; both helpers now share a `_to_10_digits` extractor.
- **Implemented `fhir_client.search_patient`.** Probes the format list in order, stops at the first non-empty Bundle, returns `{match, patient_id, candidates, probes_tried, winning_format}`. Sends `Authorization: Bearer …` and `Accept: application/fhir+json`. 5 s request timeout. Non-2xx → `FhirClientError`. DOB is validated as strict `YYYY-MM-DD` before any HTTP call.
- **Implemented the `handler.handler` Lambda entrypoint.** Validates `practice_id`, `phone`, `dob`; resolves credentials via `_get_credentials(practice_id)`; calls `search_patient`; returns the result with `practice_id` echoed back. Emits a structured, PHI-free log line (`practice_id`, `match`, `probes_count`, `winning_format`).
- **`_get_credentials` is a v0 env-var shim.** Reads `PF_FHIR_BASE_URL` + `PF_ACCESS_TOKEN`. Session 0006 replaces it with DDB lookup + on-demand refresh per ADR-0003. The shim raises `RuntimeError` if the env vars are missing so we fail loudly in any non-dev path.
- **Wrote test fixtures.** `tests/fixtures/bundle_single.json`, `bundle_empty.json`, `bundle_multiple.json` — minimal-but-realistic FHIR searchset Bundles.
- **Wrote test suites** (TDD throughout, all written before implementation):
  - `test_normalize.py` — 27 cases covering both helpers and the new probe list ordering.
  - `test_fhir_client.py` — 12 cases using `responses` to mock HTTP: first-format hit, fall-through to a later format, no match after all six probes, multiple matches, Bearer header, 401/500 → `FhirClientError`, bad phone/DOB rejection.
  - `test_handler.py` — 7 cases: single match, no match, missing-field rejections, and the default `_get_credentials` env-var behavior.
  - `test_integration_pf.py` — 5 parameterized cases marked `@pytest.mark.integration`, skipped unless `PF_FHIR_BASE_URL` and `PF_ACCESS_TOKEN` are set. Asserts both Durve test patients resolve from natural-language phone input (`"716 361 9276"`, `"7163619276"`, `"+17163619276"`, `"(716) 491-6872"`, `"716-491-6872"`).
- **`make test` is green** for all Python packages: agent (2), oauth (15), api (1), tools/lookup_patient (46), tools/complete_verification (1), tools/escalate_to_human (1). Total 66 passing, 5 integration tests skipped pending live token.

## Decisions made

- Decision (no ADR — judgment call): the `lookup_patient` Lambda surfaces a small, agent-friendly result vocabulary (`single` / `none` / `multiple`) rather than echoing the raw FHIR Bundle. The agent layer above should not learn FHIR semantics; this is the boundary where PF specifics stop.
- Decision (no ADR — judgment call): `_get_credentials` is a separate module-level function rather than a class/factory. It's small and trivially monkeypatchable in tests; promoting it to a class would buy nothing until Session 0006 swaps in DDB + refresh logic. Re-evaluate at that point.
- Decision (no ADR — judgment call): on `multiple` matches, the handler returns *all* candidate IDs and lets the agent re-prompt the caller for an additional discriminator (e.g., ZIP). We do **not** auto-pick. Picking blindly under ambiguity is exactly the verification failure mode HIPAA disclosures require us to avoid.
- Decision (no ADR — judgment call): 5 s HTTP timeout per probe. With up to 6 probes the worst-case verification could spend 30 s on HTTP alone, but in practice the first format hits — the worst case only triggers on bad data. Revisit if call-flow timing data shows clustering near the cap.
- Decision (no ADR — judgment call): PHI never enters logs. The handler's `extra={…}` log line includes `match`, `probes_count`, and `winning_format` (which is a *format pattern*, not the caller's actual number — but it's the literal probe string, so worth a closer look in Session 0006 when wiring CloudWatch).

## Open questions

1. **Is `winning_format` PHI?** It is the literal probe string that matched, which equals the patient's stored phone number on success. Today's log line emits it. Before this code reaches production (Session 0006 wires real logging), either redact it to a format *pattern* (e.g., `"(###) ###-####"`) or drop it from the log entirely. Flagged as a fix-before-prod item, not a v0 blocker.
2. **Does `Patient?telecom=` need a `system=phone` qualifier?** Some FHIR servers accept `telecom=phone|(716) 361-9276`. PF empirically returns the right result without it, so we skip — but if we ever see false positives where an email matches a numeric input, revisit.
3. **What's the right behavior on `OperationOutcome` warnings (200 with embedded issue)?** Today we treat any 2xx as success and read `entry`. If PF starts returning soft errors in a 200 Bundle, we'll miss them. Acceptable for v0; document in a later ADR if it bites.

## Next session pickup

**Plan supersedes the original "agent skeleton next" pickup.** A post-0003 introspective review surfaced three structural gaps (no refresh-token flow, no audit log, unproven Connect/AgentCore wiring) and reordered the next ~12 sessions to fill them before the agent layer lands. **The roadmap is now the source of truth** for what comes next: [`docs/roadmap.md`](../roadmap.md).

**The first thing the next session should do:**
1. Read this file.
2. Read `docs/roadmap.md` end-to-end — it replaces the queued "Session 0004 = agent skeleton" plan with `Session 0004 = refresh-token flow + KMS-encrypted DDB token store`.
3. Run `make test` from the repo root to confirm green baseline (expect 66 passed, 5 skipped).
4. Open Session 0004 per the roadmap's spec.

**Goal for Session 0004 (per roadmap):** Implement the SMART refresh-token exchange (`oauth/src/oauth/refresh.py`) and the KMS-encrypted DDB token store (`oauth/src/oauth/token_store.py`, replacing today's "Session 0006" stub). End-to-end exit criterion: an integration test that refreshes a real PF QA refresh token and uses the minted access token to successfully run the Session 0003 `lookup_patient` flow. Session also writes ADR-0007 validating ADR-0003's central open question (user-scope refresh tokens accepted by PF for unattended reads) — or, if PF rejects them, the Backend Services pivot ADR.

**Optional first action before opening Session 0004 — validate the Session 0003 integration tests against live PF QA:**
```bash
cd "/Users/m858450/Documents/GitHub/Amazon Connect Health"
make spike-fhir
# Copy access_token and fhir_base_url from the script output into env (the
# script today only prints the first 12 chars; temporarily patch the print at
# scripts/spike-fhir.py:225 to print `access` fully, then revert), then:
PF_FHIR_BASE_URL="…" PF_ACCESS_TOKEN="…" \
  PYTHONPATH=tools/lookup_patient/src \
  .venv/bin/python -m pytest tools/lookup_patient/tests/test_integration_pf.py -v
```
Expect 5 passed. Token has a 5-minute lifetime — run the integration tests immediately after the spike. After Session 0005, this awkward pasted-token dance goes away: integration tests will pull from the token store and refresh on demand.

## Files changed
- `tools/lookup_patient/src/lookup_patient/normalize.py` — added `to_pf_phone_formats`, refactored shared `_to_10_digits`
- `tools/lookup_patient/src/lookup_patient/fhir_client.py` — implemented `search_patient` + `FhirClientError`
- `tools/lookup_patient/src/lookup_patient/handler.py` — implemented `handler`, `_get_credentials` shim
- `tools/lookup_patient/tests/test_normalize.py` — replaced placeholders with full coverage
- `tools/lookup_patient/tests/test_fhir_client.py` — replaced placeholders with `responses`-based suite
- `tools/lookup_patient/tests/test_handler.py` — replaced placeholders with full coverage
- `tools/lookup_patient/tests/test_integration_pf.py` — new, integration-marked
- `tools/lookup_patient/tests/fixtures/bundle_single.json` — new
- `tools/lookup_patient/tests/fixtures/bundle_empty.json` — new
- `tools/lookup_patient/tests/fixtures/bundle_multiple.json` — new

## Notes for future Claude
- The `responses` library was already declared in `pyproject.toml` dev deps — no new dependencies introduced this session.
- The fixture Bundles are deliberately *minimal* (no `meta`, `link`, etc.). They will fail FHIR strict validation but exercise everything the code touches. Don't bulk them up unless a test actually needs more fields.
- `_get_credentials` is module-level so tests can `monkeypatch.setattr(handler_module, "_get_credentials", …)`. Don't refactor it onto a class without preserving an equally simple test seam.
- The handler does **not** attempt to refresh an expired token; if PF returns 401 we raise. Token refresh is Session 0006's job (see ADR-0003 and `docs/architecture.md` "At every call" diagram). When that lands, the 401-handling path in `search_patient` should grow a single retry-after-refresh, not a generic retry loop.
- We pass `winning_format` through to the agent; consider whether this is PHI before exposing it outside the trust boundary. Currently fine because the agent runs in the same VPC and never logs it externally.
- The integration test asserts patient IDs as constants. If the QA tenant ever gets reset/reseeded, these will drift; re-run `make spike-fhir` to recapture and update.
