# ADR-0007: User-scope refresh tokens work for unattended Practice Fusion reads (provisional pending live validation)

**Status:** Accepted (validated 2026-05-23, end of Session 0004).
`oauth/tests/test_integration_refresh.py::test_refresh_mints_access_token_that_validates_adr0003`
ran green against PF QA: a refresh-minted access token successfully
retrieved patient `b79082d9-548c-454e-9fc7-ce19ab630776` via the
unattended `Patient?telecom=&birthdate=` path, with no clinician
present. ADR-0003 stands; the Backend Services pivot is not needed.

**Date:** 2026-05-23 (Session 0004)

## Context

ADR-0003 chose the SMART **Provider App** pattern (`authorization_code`
+ PKCE, `user/` scopes) over **Backend Services** (`client_credentials`,
`system/` scopes). Its central open question:

> Does Veradigm allow `user/` scope tokens to be used in unattended
> (phone-time) contexts? Some SMART servers consider that pattern
> out-of-policy and require Backend Services for it.

Session 0002 partially answered this — but only with an access token
*minted during the original OAuth grant*, while the provider was still
in front of the browser. That is the *attended* case; the real risk
is whether PF distinguishes attended from unattended at the moment a
refresh-token-minted access token tries to call `Patient?telecom=…`
with no clinician present.

Session 0004 added the refresh-token exchange code and the
KMS-encrypted DDB token store. The new integration test exercises
exactly the unattended path:

1. Read a persisted refresh token (granted hours/days earlier).
2. POST `grant_type=refresh_token` to PF's `token_endpoint`.
3. Use the *minted* access token (not the original-grant one) to
   call `GET {base}/Patient?telecom=…&birthdate=…`.

This is the production runtime path described in `docs/architecture.md`.

## Decision

Until the integration test runs green against PF QA, ADR-0007 is
**provisional**. The implementation work needed to validate it is
shipped this session; the validation itself requires:

1. One manual `make spike-fhir` run to obtain a fresh refresh token.
2. Setting `PF_REFRESH_TOKEN`, `PF_CLIENT_ID`, `PF_CLIENT_SECRET`,
   `PF_FHIR_BASE_URL` in the shell.
3. Running `pytest oauth/tests/test_integration_refresh.py -v`.

A green test promotes this ADR to Accepted and keeps ADR-0003 standing.
A 401 / `invalid_grant` / `unauthorized_client` failure triggers a
pivot ADR-0007a documenting the Backend Services migration: regenerate
client registration with `system/` scopes, swap the
`authorization_code` onboarding flow for the JWKS-based
`client_credentials` flow, and re-write `oauth/refresh.py` and
`oauth.token_store` to fit (Backend Services has no refresh — the
client mints a JWT and exchanges it for a fresh access token every
~5 minutes).

## Why this still gets an ADR even though it's provisional

The implementation choices in Session 0004 commit to the Provider App
path: refresh-token TTL handling, rotating-vs-non-rotating refresh,
KMS-encrypted DDB row shape. If we pivot, all three change. Writing
the ADR now (a) makes the commitment legible, (b) names the validation
gate, and (c) reserves the next ADR number for the pivot so the
roadmap's session-0004 description doesn't need to be rewritten.

## Consequences if the validation fails

**Code changes:**
- `oauth/refresh.py` is replaced with `oauth/jwt_assertion.py`
  (sign-and-exchange flow).
- `oauth.token_store` keeps the access-token row but drops
  `refresh_token_ciphertext`. Schema migration is trivial — one row
  per practice, can be re-keyed in place.
- `scripts/spike-fhir.py` retained for documentation; superseded by a
  new `scripts/spike-backend-services.py`.

**Onboarding changes:**
- Practices register us as a Backend Services client (different
  Veradigm onboarding flow). One ADR change, one runbook change.

**Why we still prefer Provider App when both work:**
- Audit attribution to a real clinician (per ADR-0003).
- Lower per-practice onboarding friction.
- No JWKS key rotation to operate.

## Validation criteria

`pytest oauth/tests/test_integration_refresh.py -v` returns 1 passed,
0 skipped, 0 failed against PF QA. Promote to Accepted with the date
of that run noted in this ADR.
