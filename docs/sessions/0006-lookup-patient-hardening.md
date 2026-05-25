# Session 0006 — `lookup_patient` hardening: refresh wire-in, audit, rate limit

**Date:** 2026-05-23
**Goal (one sentence):** Make `lookup_patient` production-shaped — per-practice
credentials with transparent refresh, one HIPAA audit record per FHIR probe,
per-(practice, ANI) rate limit — and lock in the multi-env CDK pattern that
will carry every later stack.

## What was done

### New `audit/` package
- `audit.disclosure_log.record(...)` — writes one S3 object per FHIR
  call. Schema: `practice_id`, `call_id`, `timestamp`, `tool`,
  `query_template` (a *pattern*, never the raw value),
  `result_resource_ids`, `disclosed_fields`. Refuses to write if the
  template looks like raw PHI (defensive ``PhiLeakError``).
- `audit.rate_limit.check_and_increment(practice_id, ani, max_per_day)`
  — single DDB ConditionalUpdate, atomic increment + budget gate per
  (practice, ANI, day-bucket). Over-budget raises ``RateLimitExceeded``.
- 10 unit tests across both modules via `moto[s3,dynamodb,kms,secretsmanager]`.

### `oauth/` extensions
- `oauth.refresh.InvalidGrantError` (subclass of ``RefreshTokenError``) —
  signals "the stored refresh token is no longer valid; reconnect required."
  Triggered by 400 + body `{"error": "invalid_grant"}`. Two new tests cover
  the new branch and confirm other 400s stay generic.
- `oauth.token_store.update_access_token(practice_id, access_token, *, expires_at)`
  — partial-update path for the no-rotation refresh case. Saves a KMS
  encrypt + one DDB write column versus a full `put`. Verified by a new
  unit test that asserts the refresh-token column is untouched.
- `oauth.practices_store.PracticesStore` (new) — per-practice config lookup
  (DDB read-only). Returns `fhir_base_url`, `token_endpoint`, `pf_client_id`,
  `pf_client_secret_arn`. Writes are owned by the OAuth onboarding API
  (Session 0008).
- `oauth.client_secret_provider.resolve(secret_arn)` (new) — fetches the
  plaintext PF client secret from Secrets Manager. No caching — relies on
  Lambda execution-context reuse instead of a custom cache that would
  go stale on rotation.

### `tools/lookup_patient/` rewrite
- `handler._get_credentials(practice_id)` is the new credential resolver:
  reads from `practices_store` + `token_store`, refreshes if the cached
  access token is within 60 s of expiry, and handles three branches:
  1. **No rotation** (PF default per Session 0004): `update_access_token`
     — one column writeback.
  2. **Rotation detected** (PF returns new `refresh_token`, OR provider
     re-authorized via `/callback` between two of our refreshes): full
     `put` — both columns rewritten.
  3. **`invalid_grant`**: `mark_needs_reconnect`, raise
     `CredentialsExpired`. Handler returns `match: "credentials_expired"`.
- `fhir_client.search_patient` gains two optional seams:
  - `on_probe` callback — invoked once per probe HTTP call. Used by
    the handler to write one audit record per probe; keeps audit-domain
    knowledge out of the FHIR client.
  - `refresh_access_token` callback — invoked **once** on a 401 to mint
    a fresh token; the same probe is retried with the new bearer. After
    a single refresh, 401s are permanent for the lookup.
- Rate-limit gate is the **first** thing the handler does — before
  credentials, before any FHIR call. Over-budget returns
  `match: "rate_limited"` (ADR-0009 — leak-resistance).
- **Env-var shim removed.** `PF_ACCESS_TOKEN` / `PF_FHIR_BASE_URL` no
  longer read by the handler. The single-practice mode they propped up
  in Session 0003 is gone; multi-tenant from this commit forward.
- Test suite rewritten around a `mock_aws` fixture that seeds practices
  + tokens + secret + KMS key + rate-limit table + audit bucket. 11 unit
  tests covering: happy paths, rate-limit, 401 retry, invalid_grant,
  rotation detected, audit-record-per-probe (the first failing test).

### Integration tests (svc-integration layer)
- `tools/lookup_patient/tests/test_integration_handler.py` (new): full
  vertical-slice handler invocation against live PF QA. AWS services
  are moto-mocked, real HTTP goes out to PF for SMART discovery,
  refresh-grant, and Patient search. Asserts the handler returns a
  `single` match, the audit bucket has one record per probe with no
  PHI in the body, and the token store is in `active` state with a
  refreshed access token.
- `tools/lookup_patient/tests/conftest.py` (new): session-scoped
  `pf_access_token` fixture mints once per pytest session. Reason:
  **PF invalidates prior access tokens when a new refresh-grant
  happens** (empirical, Session 0006 finding). The existing
  `test_integration_pf.py` ADR-0006-validation tests share this token
  so they don't get burned by the handler test's mid-session refresh.

### CDK (multi-env structure + first two real stacks)
- `infra/config/envs.ts` (new): per-env config registry. Three
  entries: `qa` (account `086514900943`, populated), `staging` and
  `prod` (account `TBD`). `loadEnv()` rejects unknown names and any
  env whose account is `TBD`.
- `infra/bin/app.ts` rewritten to read env from `--context env=…`
  (fallback `CDK_ENV`), call `loadEnv()`, and instantiate stacks with
  env-suffixed names + `envConfig` in props.
- `infra/lib/audit-stack.ts` (new): S3 audit bucket with Object Lock
  (compliance mode, 7-year retention) + dedicated KMS CMK (rotation
  enabled) + public-access-block + SSL-only. Removal policy follows
  `EnvConfig.removalPolicy` — `DESTROY` in QA, `RETAIN` in prod.
- `infra/lib/rate-limit-stack.ts` (new): PAY_PER_REQUEST DDB table
  partitioned by `(pk, bucket)` with TTL on `expires`. PITR enabled
  in prod only.
- `infra/test/infra.test.ts` rewritten — 9 jest tests covering env
  config loading, stack-level resource shape (KMS rotation, Object
  Lock retention/mode, bucket public-access-block, table TTL), and
  the env-specific removal policies.
- `cdk synth --context env=qa` runs clean; `--context env=staging`
  fails fast on the TBD account (as designed).

### Makefile
- `audit` added to `PYTHON_PKGS` so its unit tests run in the harness.

### ADRs
- **ADR-0008: Multi-environment CDK structure (`qa` / `staging` / `prod`).**
  Locks in the env-context + `envs.ts` + env-suffixed stack name pattern
  *before* any stack code lands. Written first this session, on purpose.
- **ADR-0009: HIPAA audit log + rate limit at the tool boundary.**
  Documents one-record-per-probe vs. one-per-lookup, why rate-limit
  surfaces as a normal `match` outcome (leak-resistance), and the
  ``on_probe`` callback seam in the FHIR client.

### Result
- **`make test-ci` green, all four layers, with the binding gate in force
  from this commit forward (Principle #2).**
- Unit layer: 109 Python tests (was 88) — net +21 across audit (10),
  oauth (8), lookup_patient (4 net; 11 new minus 7 deleted/superseded);
  + 9 jest tests (was 1) — net +8 CDK snapshot tests.
- svc-integration layer: 7 tests (was 6) — net +1 (full-handler against
  real PF QA, exercising rate-limit + practices_store + token_store +
  KMS + Secrets Manager + refresh + audit + Patient search end-to-end).

## Decisions made

- **ADR-0008** — multi-env CDK pattern. Written before any stack
  introduced this session.
- **ADR-0009** — audit + rate-limit live at the tool boundary, one
  record per FHIR probe, rate-limit surfaces as `match` not exception.
- **Practices store table is read-only this session** (no ADR — judgment
  call). Writes belong to the OAuth onboarding API (Session 0008). We
  seed rows in tests; production writes come later.
- **Client secret resolver has no in-process cache** (no ADR — judgment
  call). Lambda execution-context reuse already caches the boto3
  client; adding our own cache would go stale on secret rotation.
- **Rate-limit ConditionalUpdate increments *then* gates** (no ADR —
  judgment call). Pre-check + increment would race; the slight
  rounding (over-budget kicks in at 101, not 100) is acceptable.
- **Audit failures do not block FHIR calls** (no ADR — judgment call).
  HIPAA requires the disclosure *be recorded*, not that the disclosure
  be blocked on the recorder. An S3 PutObject failure logs + alarms
  but doesn't kill the lookup. Alarm + DLQ wiring is Session 0016.
- **Object Lock is compliance-mode, 7-year retention** (no ADR —
  follows HIPAA default and is the more conservative choice; governance
  mode would let an admin bypass the lock, which defeats the property).
- **`autoDeleteObjects: false` even in QA** (no ADR). Object Lock
  blocks deletes anyway; setting it to true produces a confusing CDK
  failure when destroying the QA stack. The bucket has to be emptied
  manually only if the lock window has expired.

## Open questions

1. **Per-practice rate-limit overrides.** When a real practice hits
   100/day legitimately, how do they get a higher cap? Plausible: a
   column on the practices row. Defer until a practice asks.
2. **AWS SSO + CLI setup.** The svc-integration layer locally + in CI
   runs purely with moto (no AWS account). Session 0007's CDK deploy
   needs real AWS credentials against account `086514900943`. Set up
   `aws sso login` + bootstrap before opening 0007 to avoid a blocking
   detour.
3. **PF access-token invalidation on refresh.** New finding this
   session: PF invalidates the prior access token when a refresh-grant
   exchange happens (some servers do, some don't). Confirmed
   empirically by the integration test ordering. Operational
   consequence: two Lambdas refreshing for the same practice within
   seconds of each other will each invalidate the other's prior
   token. Today's 60-s leeway makes this unlikely; if call-concurrency
   per practice grows, we'd need a per-practice refresh lock. Not yet
   a problem.
4. **Audit-bucket read access for practices.** Today only the
   compliance role can read. Decide when a practice asks.

## Next session pickup

**The first thing the next session should do:**

1. Read this file (especially the "Decisions made" block — ADR-0008
   constrains *every* stack 0007 introduces, and the empirical
   refresh-invalidates-prior-access-token finding shapes how
   AgentCore should obtain credentials).
2. Read `docs/roadmap.md` Session 0007 entry — Connect + AgentCore +
   Nova Sonic plumbing spike.
3. Run baseline:
   ```sh
   make test-ci      # all four layers green
   ```
4. **Verify AWS CLI is set up** — Session 0007 is the first session
   that deploys real CDK. You'll need:
   ```sh
   aws configure sso          # one-time, against account 086514900943
   aws sso login              # per-day
   aws sts get-caller-identity # confirm
   cd infra
   npx cdk bootstrap aws://086514900943/us-east-1   # one-time per account+region
   ```
5. ADR-0008 means every CDK invocation in 0007+ takes
   `--context env=qa` (or fallback `CDK_ENV=qa`).

**Goal for Session 0007 (per roadmap):** Real phone call → Connect
contact flow → KVS → AgentCore Runtime → Nova Sonic → "hello, you
reached the verification agent" → hang up. No real agent logic, no
FHIR calls. Just the wire.

**Exit criteria for Session 0007** (per roadmap):
- `infra/lib/connect-agentcore-stack.ts` synthesizes cleanly using
  ADR-0008's env-context pattern.
- Stack deployed to account `086514900943` via `cdk deploy`.
- Real phone call against the provisioned DID produces a greeting
  and a hangup.
- `docs/runbooks/connect-bootstrap.md` documents the manual steps
  (DID purchase, BAA, Nova Sonic enablement, AgentCore region).
- ADR-0010 documenting any wire-format surprises.

**Prerequisite blocks before opening 0007:**
- AWS BAA confirmed for account `086514900943` (CLAUDE.md callout).
- AgentCore region availability for our account confirmed.

## Files changed

- `audit/pyproject.toml`, `audit/src/audit/{__init__.py,disclosure_log.py,rate_limit.py}`,
  `audit/tests/test_disclosure_log.py`, `audit/tests/test_rate_limit.py` — new package
- `oauth/src/oauth/refresh.py` — `InvalidGrantError` + 400/invalid_grant branch
- `oauth/src/oauth/token_store.py` — `update_access_token` method
- `oauth/src/oauth/practices_store.py` — new
- `oauth/src/oauth/client_secret_provider.py` — new
- `oauth/tests/test_refresh.py` — 2 new tests
- `oauth/tests/test_token_store.py` — 1 new test
- `oauth/tests/test_practices_store.py` — new, 3 tests
- `oauth/tests/test_client_secret_provider.py` — new, 2 tests
- `tools/lookup_patient/src/lookup_patient/handler.py` — rewrite
- `tools/lookup_patient/src/lookup_patient/fhir_client.py` — `on_probe` + 401-retry seams
- `tools/lookup_patient/tests/test_handler.py` — rewrite, 11 tests
- `tools/lookup_patient/tests/test_integration_handler.py` — new
- `tools/lookup_patient/tests/test_integration_pf.py` — switched to shared
  `pf_access_token` fixture
- `tools/lookup_patient/tests/conftest.py` — new, session-scoped fixture
- `tools/lookup_patient/pyproject.toml` — adds moto + secretsmanager dev dep
- `infra/config/envs.ts` — new
- `infra/bin/app.ts` — rewritten, env-context aware
- `infra/lib/audit-stack.ts`, `infra/lib/rate-limit-stack.ts` — new
- `infra/test/infra.test.ts` — rewritten, 9 tests
- `infra/tsconfig.json` — includes `config/**`
- `Makefile` — `audit` added to `PYTHON_PKGS`
- `docs/decisions/0008-multi-environment-cdk-structure.md` — new
- `docs/decisions/0009-audit-and-rate-limit-at-tool-boundary.md` — new

## Notes for future Claude

- **PF invalidates prior access tokens on refresh.** This is a real
  thing. The `pf_access_token` session-scoped fixture in
  `tools/lookup_patient/tests/conftest.py` exists for exactly this
  reason. If a future session adds another integration test that
  refreshes against PF mid-run, give it the same treatment.
- **`update_access_token` is the hot path.** Session 0004 confirmed PF
  doesn't rotate refresh tokens; this method exists so the common
  refresh write is one column, one KMS encrypt. The defensive
  `put`-on-rotation branch in `_get_credentials` exists but should be
  rare in PF QA.
- **`build_app` in `api/`** still has only `/healthz`. Session 0008
  extends it with OAuth onboarding routes — additive, not a rewrite
  (Session 0005 already converted it from a `NotImplementedError`
  stub to a real factory).
- **The audit recorder doesn't sign / chain records.** Object Lock
  compliance mode provides the tamper-evidence at the storage layer.
  If we ever need an additional cryptographic chain (e.g., for an
  external auditor's higher-assurance bar), it lives outside this
  module — don't entangle the writer with it.
- **`refresh_access_token`'s ``InvalidGrantError`` is a *subclass* of
  ``RefreshTokenError``.** Existing callers that `except
  RefreshTokenError` still work unchanged. New code that wants to
  distinguish should match on the specific subclass first.
- **`fhir_client.search_patient`'s 401 retry refreshes once, full stop.**
  A second 401 after the refresh is permanent — no second retry. If a
  practice's token genuinely became invalid mid-call, we'd rather fail
  the lookup quickly than thrash.
- **Multi-env CDK is binding.** Any new stack from Session 0007 onward
  must follow the ADR-0008 pattern (env in props, env-suffixed name,
  no env-name branching in Lambda code). If a future session is
  tempted to add a one-off un-prefixed stack, point them at
  `docs/decisions/0008-multi-environment-cdk-structure.md`.
- **The integration test for the full handler flow is the keystone.**
  It exercises practices_store, token_store, KMS, Secrets Manager,
  refresh against real PF, rate-limit, audit, AND the FHIR search —
  one test asserts the whole vertical slice works against the
  real upstream. If that test ever flakes, *don't* dial back its
  scope; figure out which seam regressed.
