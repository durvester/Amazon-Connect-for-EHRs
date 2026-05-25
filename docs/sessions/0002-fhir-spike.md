# Session 0002 — PF FHIR OAuth spike

**Date:** 2026-05-23
**Goal:** Prove we can authenticate with Practice Fusion (QA) via SMART-on-FHIR `authorization_code` + PKCE and retrieve at least one test patient by phone + DOB.

## What was done

- **Probed PF QA discovery endpoint** (`/.well-known/smart-configuration`). Confirmed it returns standard SMART metadata including `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `introspection_endpoint`, `capabilities`, `grant_types_supported`, `code_challenge_methods_supported=["S256"]`. The full response is captured in the well_known test fixtures.
- **Captured the live FHIR CapabilityStatement** at `docs/research/pf-capabilitystatement.json` (104 KB). FHIR 4.0.1, US Core server profile. Confirmed `Patient` supports `read` + `search-type` interactions and exposes `telecom` (token) and `birthdate` (date) as search params — exactly the verification query shape.
- **Implemented `oauth.well_known.fetch_smart_configuration`** test-first with the captured PF response shape as the primary fixture. 6 new unit tests pass; full `oauth/` suite is 15 green.
- **Wrote `scripts/spike-fhir.py`** — end-to-end OAuth spike: loads `.env`, runs SMART discovery, generates a PKCE pair, starts a one-shot listener on `http://localhost:8080/oauth/callback`, opens the browser to PF's authorization endpoint, exchanges the returned code (with `client_secret` and PKCE verifier) at the token endpoint, then calls `GET {base}/Patient?telecom=&birthdate=` for any test patients with phone+DOB filled into `.env`. Writes a structured summary to `docs/research/spike-fhir-result.json`.
- **Hardened the Makefile** to use a venv (PEP 668 macOS Homebrew compatibility). Added `make spike-fhir` and `make test` targets that work end-to-end. `make test` now passes 34 Python tests across all packages.

## Empirical findings (running the spike against PF QA)

1. **`fhirUser` is camelCase per the SMART spec.** PF rejected `fhiruser` at the authorize step. Our initial `.env` had the lowercase form; fixed. Documented in `.env.example`.
2. **Do NOT include `launch` scope in standalone-launch flow.** PF accepts it at `/authorize` (issues an auth code) but then **rejects at `/token`** with `403 {"subcode":"Forbidden","message":"Invalid launch context"}`. The `launch` scope requires an EHR-launch context (a `launch={id}` parameter), which standalone apps don't have. Removed from `.env`; flagged in `.env.example`.
3. **Access tokens are short — `expires_in: 300` (5 minutes).** Refresh tokens are mandatory for any production use; we already store them per ADR-0003 architecture.
4. **All 19 requested scopes were granted as-is.** Token endpoint echoed the full scope list back. `user/Patient.read` confirmed available.
5. **Discovery, authorization, and token exchange all worked over straightforward HTTPS** — no Veradigm-specific headers, no JWKS asymmetric auth (we used `client_secret_post`). PF's SMART implementation appears to follow the spec faithfully on these endpoints.
6. **PF returns `pfCorrelationId` on errors** — capture it in production logs for support escalations.
7. **PF's `Patient?telecom=` search is *literal string match* against the stored value, not normalized phone matching.** Probed five format variants against both test patients; only the exact stored format `(NPA) NXX-XXXX` and a re-built `(NPA) NXX-XXXX` from digits matched. `7163619276`, `+17163619276`, and `716-361-9276` all returned zero. **This invalidates our original plan to normalize caller input to E.164 before querying.** Captured in [ADR-0006](../decisions/0006-pf-telecom-search-is-literal.md).
8. **Name search works robustly** — `Patient?family={last}&given={first}` returned exact matches for both Durve patients. Useful as a fallback if a phone-format probe set misses.
9. **Verification flow exit criterion met (with the format fix).** Both Durve patients successfully retrieved via the verification-style `telecom + birthdate` query using PF's stored format — confirming the end-to-end pipeline works once we use the right format.

Full spike summary at [`docs/research/spike-fhir-result.json`](../research/spike-fhir-result.json).

## Decisions made

- Decision: SMART discovery endpoint is queried at runtime (no caching in v1). Cheap, easy to debug, no staleness risk. (No ADR — judgment call.)
- Decision: spike-fhir.py is stdlib + `requests` only, no FastAPI dependency. The script is throwaway; production OAuth callback runs on Lambda/API Gateway in Session 0006.
- Decision: `.env` parsing is a tiny in-script parser (no `python-dotenv` dep). Same rationale — spike script, no transitive deps to lock down.
- Decision: PKCE method is hardcoded `S256` (PF only supports S256 per discovery — verified empirically). No ADR needed.
- Decision: client authentication at the token endpoint uses `client_secret_post` (creds in request body) rather than HTTP Basic. PF accepted this. Either works; chose body to keep the spike's `requests.post(data=...)` call simple.

## Open questions

1. **Are user-scope tokens accepted by PF for unattended runtime reads?** ADR-0003 stands until contradicted. We will know empirically as soon as the user completes the OAuth flow and we make the Patient lookup. If the lookup works with the user-scope token, ADR-0003 is validated for this stage at least.
2. **Test patient `phone` and `dob`** still missing from `.env` (entries for Mohit Milind Durve and Ayesha Durve have name but not phone/dob). Without them the spike will print "skipped (phone or dob missing)" — token exchange will still succeed; lookup will not.
3. **`launch` scope behavior** — we requested it as registered with Veradigm even though we use the standalone-launch capability. Verify the auth flow accepts the scope set as-is; PF may silently strip `launch` for standalone, which is fine.

## Next session pickup

**Status as of end of Session 0002:** the spike script is implemented and tested. The user needs to run it interactively to complete the OAuth flow against PF QA and see the patient lookup result. Once that runs successfully, Session 0003 (implement the real `lookup_patient` Lambda) can begin.

**Two commands for the user to finish Session 0002 themselves (or for the next Claude session to walk through):**

```bash
cd "/Users/m858450/Documents/GitHub/Amazon Connect Health"

# (optional, only if patient lookup should succeed) add to .env:
#   PF_TEST_PATIENT_1_PHONE=<E.164 or any common US format>
#   PF_TEST_PATIENT_1_DOB=YYYY-MM-DD

make spike-fhir
```

The script will:
1. Print discovery results.
2. Open a browser to PF QA's authorization page.
3. The user signs in and grants the scopes.
4. PF redirects to `http://localhost:8080/oauth/callback`.
5. The script exchanges the code, prints token details (token_type, expires_in, refresh_token present?, scope echoed back).
6. For each test patient with phone+DOB filled in, runs `Patient?telecom=&birthdate=` and prints the result (Bundle total + matched Patient IDs).
7. Writes `docs/research/spike-fhir-result.json`.

**Goal for Session 0003 (now that spike has succeeded):**
Implement the real `lookup_patient` Lambda end-to-end (handler.py, fhir_client.py) test-first against recorded fixtures, then validate with the live PF QA token. **Key behavioral change vs. the original plan:** the phone-input normalization in `lookup_patient/normalize.py` will be reworked to produce **PF storage formats** (`(NPA) NXX-XXXX` first, then dashed, digits-only, etc. as fallback probes) instead of E.164. See [ADR-0006](../decisions/0006-pf-telecom-search-is-literal.md). The existing `normalize_e164` function stays as a utility for other code paths (audit-log redaction, etc.) but is no longer the FHIR-query formatter.

The `phone="(716) 361-9276"` / `dob="1991-06-09"` lookup for Mohit, and `(716) 491-6872` / `1991-06-09` for Ayesha, both confirmed returning 1 match. Use these as the integration-test ground truth in Session 0003.

**If the spike fails:**

- **Token exchange returns 401/400** — most likely scope or client-secret encoding issue. Check the exact `scope` parameter format PF expects (space-separated should be standard). Try moving client_secret from request body to HTTP Basic auth header.
- **Authorization redirect throws "invalid scope"** — PF doesn't recognize one of the requested scopes. Drop scopes one at a time to find which (most likely `launch` or `fhiruser`).
- **Browser sees a "no such app" error** — confirm `PF_CLIENT_ID` matches what Veradigm registered, and that the redirect URI in `.env` matches exactly what's on file with Veradigm.
- **Patient lookup returns 0 matches** — try `Patient?telecom={phone}` (no birthdate); if that finds nothing, try `Patient?name={family-name}`. Most common cause is phone-number formatting in PF's record (we normalize to E.164; PF may store as `(555) 123-4567`).

## Files changed (created or modified)

- `oauth/src/oauth/well_known.py` — implemented (was placeholder)
- `oauth/tests/test_well_known.py` — real test coverage (was placeholder)
- `scripts/spike-fhir.py` — new
- `Makefile` — venv-aware, added `make spike-fhir`
- `docs/research/pf-capabilitystatement.json` — new, 104 KB live capture
- `docs/credentials.md` — added "Where local-dev credentials live" section + Session 1 status
- `docs/sessions/0001-bootstrap.md` — resolved questions, updated pickup
- `.env` — hydrated with PF QA values (gitignored)
- `.env.example` — new (committed)

## Notes for future Claude

- All Python tests pass (34 of them). Run `make test` from the repo root to verify.
- `.venv/` lives at the repo root and is gitignored. The Makefile creates it on demand.
- The spike script's helpers (PKCE generation, SMART discovery, phone normalization) are imported from the real packages — they have unit tests. The spike script itself is intentionally not tested (it's interactive).
- PF QA's discovery + CapabilityStatement endpoints are unauthenticated; both can be re-probed any time with plain curl. Useful for debugging.
- `client_credentials` is also in PF's `grant_types_supported`. If user-scope unattended access turns out to be a problem, the Backend Services pivot per ADR-0003 is open.
- A real Veradigm dev portal isn't documented publicly; the user is the source of truth for credentials and scope strings.
- The CapabilityStatement is dated `2025-06-12` — a year out of date relative to today (2026-05-23). PF may have updated their FHIR server since; re-fetch and diff if anything mysteriously breaks later.
