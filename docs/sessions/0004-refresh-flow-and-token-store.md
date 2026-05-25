# Session 0004 — Refresh-token flow + KMS-encrypted DDB token store

**Date:** 2026-05-23
**Goal:** Implement the SMART refresh-token exchange and persistent
encrypted token storage, so any Lambda can call PF with a current
access token without provider re-login — and so ADR-0003's central
open question can be answered against the production runtime path.

## What was done

- **Added `oauth.refresh.refresh_access_token`** (test-first, 11 unit
  tests). Issues `grant_type=refresh_token` via `client_secret_post`
  (same auth shape PF accepted in the Session 0002 spike). Handles
  both rotating refresh tokens (response carries a new
  `refresh_token`) and non-rotating (caller's input is preserved).
  Surfaces all non-2xx, network, JSON-parse, and
  `missing-access-token` failures as `RefreshTokenError`. 10 s
  timeout.
- **Replaced the `oauth.token_store` "Session 0006" stub with a real
  `TokenStore` class** (test-first, 7 unit tests via `moto` mocking
  both DynamoDB and KMS). API:
  - `put(practice_id, access_token, refresh_token, *, expires_at)`
  - `get(practice_id) -> TokenRecord | None`
  - `mark_needs_reconnect(practice_id)`

  Both `access_token` and `refresh_token` are KMS-encrypted before
  being written to DDB. The "no plaintext on disk" guarantee is
  verified by a negative test that reads the raw DDB item and
  asserts the plaintext values do not appear anywhere in the
  serialized record. KMS-decrypt failures (e.g., wrong key, mangled
  ciphertext) surface as `TokenStoreError`.
- **Added the integration test stub
  `oauth/tests/test_integration_refresh.py`** — marked
  `@pytest.mark.integration`, skipped unless `PF_FHIR_BASE_URL`,
  `PF_REFRESH_TOKEN`, `PF_CLIENT_ID`, `PF_CLIENT_SECRET` are all set.
  When run, it (a) discovers PF's `token_endpoint` via
  `well_known.fetch_smart_configuration`, (b) refreshes, (c) uses
  the freshly-minted access token to run the Session 0003
  `lookup_patient.search_patient` flow against the Mohit Durve
  fixture, (d) asserts the patient ID matches. This is the
  validation gate for ADR-0007.
- **Added `moto[dynamodb,kms]>=5` to oauth dev deps** and registered
  the `integration` pytest marker in `oauth/pyproject.toml`.
- **Wrote ADR-0007** and then **validated it against live PF QA at
  end of session** — integration test ran green:
  `test_refresh_mints_access_token_that_validates_adr0003 PASSED`.
  A refresh-minted access token (not the original-grant one)
  retrieved patient `b79082d9-548c-454e-9fc7-ce19ab630776` via the
  unattended `Patient?telecom=&birthdate=` path. ADR-0003 stands.
  ADR-0007 promoted from Provisional → Accepted in the same commit.

## Empirical findings from the live validation

1. **PF does NOT rotate refresh tokens.** A second refresh-grant
   exchange returned no `refresh_token` field; the original refresh
   token continues to work. `oauth.refresh.refresh_access_token`'s
   non-rotating path is the real path; the rotating path remains
   defensive code. Session 0006's refresh-on-near-expiry logic does
   *not* need to write the refresh token back to the store on every
   refresh — only the access token and `expires_at`. Less DDB churn.
2. **Access tokens are 20 characters, `expires_in=300`** — confirmed
   the Session 0002 finding still holds.
3. **Full scope set is echoed back on refresh**, including
   `CarePlan.read`, `Encounter.read`, `DocumentReference.read`,
   `DiagnosticReport.read`. The roadmap's Session 0013/0014/0015
   tools have their scopes confirmed available on refresh-minted
   tokens (not just the original grant).
4. **PF's `token_endpoint` is per-tenant**:
   `{fhir_base_url}/token` (e.g.,
   `https://qa-api.practicefusion.com/fhir/r4/v1/{org-uuid}/token`).
   Always discover it from `.well-known/smart-configuration` rather
   than constructing it — leaks of "constant" endpoints across
   tenants would be a real bug.

## Decisions made

- Decision (no ADR — judgment call): the refresh function takes the
  `token_endpoint` URL as a parameter rather than discovering it
  internally via `well_known.fetch_smart_configuration`. Reason:
  callers in production read the practice's `fhir_base_url` from
  DDB and have already done discovery once at onboarding; caching
  the endpoint there avoids a per-call `.well-known` fetch. The
  integration test does the discovery explicitly so the runtime
  hot path stays free of it.
- Decision (no ADR — judgment call): app-layer KMS Encrypt of the
  token strings directly, rather than envelope encryption with a
  GenerateDataKey + local AES. The payload is ≤300 bytes; KMS
  Encrypt is rate-limited per CMK but the rate is more than
  sufficient for our token-write frequency (one per practice per
  ~hour at most). Direct KMS keeps the code small. Revisit if the
  per-CMK rate becomes a hotspot.
- Decision (no ADR — judgment call): if PF omits `refresh_token`
  from the response, we keep using the input refresh token. SMART
  doesn't require rotation; we have to handle both servers.
- Decision (no ADR — judgment call): `TokenStore` is a class with
  injected `table_name`/`key_id`/`region`, not a module of
  functions. The Lambda layer above instantiates once at cold-start
  and reuses. Lets tests construct fresh stores per-`@mock_aws`
  context without environment-variable juggling.

## Open questions

1. ~~Live PF QA validation.~~ **Resolved end of Session 0004** —
   integration test ran green. ADR-0007 promoted to Accepted.
2. ~~Does PF rotate refresh tokens?~~ **Resolved end of Session 0004
   — no.** PF returns no `refresh_token` field on refresh-grant
   responses; the original refresh token continues to work.
   Operational consequence: the persisted dev fixture in Session
   0005 does *not* need rotation handling, and `lookup_patient` in
   Session 0006 only needs to write back the access token +
   `expires_at`, not the refresh token. Defensive rotating code in
   `oauth.refresh` stays as-is — costs nothing and protects against
   PF changing this behavior.
3. **Refresh-token TTL.** PF's response still doesn't expose this;
   SMART leaves it optional. The token_store schema includes an
   (unused-by-this-session) `refresh_expires_at` column from
   `docs/architecture.md`. We'll learn the TTL the first time a
   practice's refresh fails with `invalid_grant` after long idle;
   `mark_needs_reconnect` then flips the row and the dashboard
   surfaces it. Listed for Veradigm in the roadmap's open questions.

## Deferred to Session 0005 (intentionally, not slop)

The roadmap's Session 0004 spec listed `secrets/pf-qa-refresh-token.enc`
and `scripts/seed-dev-refresh-token.py` as outputs of this session.
They're moved to Session 0005:

- The CI harness is the only consumer of the encrypted dev fixture.
  Building the fixture without the consumer creates a file with
  nothing reading it.
- The encryption choice (sealed-box vs. KMS) is gated on whether
  Session 0005 lands the dev KMS key before the harness needs it.
  Better made in Session 0005 with full context.
- Manual prerequisite is unchanged either way: one `make spike-fhir`
  run gates this.

This deferral is explicit and named in the next-session-pickup
below; it does not change the roadmap's principles or invariants.

## Next session pickup

**The first thing the next session should do:**
1. Read this file (especially the "Empirical findings" block — three
   PF behaviors that shape Sessions 0006+).
2. Read `docs/roadmap.md` Session 0005 entry — the CI pipeline +
   E2E test harness.
3. Run `make test` to confirm baseline (expect 84 passed, 6 skipped:
   5 lookup_patient integration + 1 oauth integration).
4. The ADR-0007 validation gate that this session's original pickup
   instructions described **has already been run, green**, at end
   of Session 0004. No work to do there before opening 0005.

**Goal for Session 0005 (per roadmap):** stand up `make test-ci` —
the four-layer CI harness (unit, service-integration, UI E2E, agent
E2E) — including the persisted dev refresh-token fixture
(`secrets/pf-qa-refresh-token.enc`) and
`scripts/seed-dev-refresh-token.py` that this session deferred. The
current `secrets/pf-qa-tokens.json` is the un-encrypted seed for
that fixture — Session 0005 encrypts it and gates CI on the
ciphertext.

**Useful state already on disk for Session 0005:**
- `secrets/pf-qa-tokens.json` — gitignored, contains the freshly-validated
  refresh token (non-rotating, so the same value works indefinitely
  modulo PF revocation), client_id, client_secret, and
  fhir_base_url. Session 0005's seed script encrypts this and writes
  `secrets/pf-qa-refresh-token.enc`.
- `scripts/spike-fhir.py` — has a `secrets/pf-qa-tokens.json` writer
  added in Session 0004. Keep it; it's the manual path when the
  refresh token does eventually expire (PF TTL still unknown — see
  open question #3).

## Files changed
- `oauth/src/oauth/refresh.py` — new
- `oauth/src/oauth/token_store.py` — replaced "Session 0006" stub
  with real `TokenStore` class
- `oauth/tests/test_refresh.py` — new, 11 cases
- `oauth/tests/test_token_store.py` — new, 7 cases (moto DDB+KMS)
- `oauth/tests/test_integration_refresh.py` — new
  (`@pytest.mark.integration`)
- `oauth/pyproject.toml` — `moto[dynamodb,kms]>=5` dev dep,
  `integration` marker registered
- `docs/decisions/0007-user-scope-refresh-tokens-validated.md` — new
  (status: Provisional)

## Notes for future Claude
- `moto` is installed but slow to import on first hit (~2 s for the
  test_token_store suite). Acceptable — moto saves us a real DDB+KMS
  in the dev loop.
- `KeyId` in `TokenStore` accepts either a key ID, an ARN, or an alias.
  Tests use `alias/...`; production CDK should pass the ARN to avoid
  alias-resolution permissions on the Lambda role.
- The integration test imports `lookup_patient.fhir_client` via
  `sys.path` munging rather than installing the tool package as a
  dep of `oauth`. Reason: oauth is a service, lookup_patient is a
  Lambda — no real package dependency exists; we just want the
  integration test to round-trip through both. If this becomes
  fragile (it won't until someone restructures the repo), promote to
  a proper test fixture package.
- `TokenStoreError` swallows both `KMSClient.exceptions.*` and
  `DynamoDB.exceptions.*` paths under one type. Callers don't need
  to distinguish; logs include the underlying `ClientError`.
- A few details deliberately *not* implemented this session:
  - `refresh_expires_at` (refresh-token TTL) — column exists in the
    architecture but PF doesn't expose it on refresh, so the field
    is omitted from `TokenRecord` until we know how to populate it.
  - 401-on-FHIR triggers refresh: that integration belongs in
    Session 0006 (lookup_patient hardening), not here.
  - Automatic refresh on `get()` if `expires_at` is in the past:
    same as above — `TokenStore` is a dumb store, the
    refresh-on-read logic is the caller's responsibility (Session
    0006).
