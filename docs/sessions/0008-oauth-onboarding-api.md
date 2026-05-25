# Session 0008 — OAuth onboarding API + DID claim

**Date:** 2026-05-23
**Goal (one sentence):** Stand up the OAuth onboarding API
(`/oauth/start` + `/oauth/callback`) so a practice can be added to the
system end-to-end — SMART authorization-code grant, KMS-encrypted token
persistence, dedicated Connect DID claim, and `phone_routing` row in
one round-trip — with `make test-ci` green and the new CDK stack
synth-clean.

## What was done

Built the onboarding API in the four pieces the design needed:

1. New plumbing modules with their own unit tests (TDD per
   [[feedback_session_handoff_tdd_harness]]):
   - `oauth.state_store` — DDB-backed single-use PKCE/state cache
   - `oauth.code_exchange` — `authorization_code` grant against PF
   - `routing.connect_provisioner` — `search_available_phone_numbers_v2`
     + `claim_phone_number` with throttling surfaced as a typed error
   - `oauth.practices_store.put()` — the write path that was deferred
     from Session 0006
2. Dependency-injected FastAPI app:
   - `api/src/api/onboarding.py` — `/oauth/start` + `/oauth/callback`
     route bodies and `OnboardingDeps` dataclass
   - `api/src/api/app.py` — `build_app(deps=...)` accepting injected
     deps; without args it constructs production deps from env vars
   - `api/src/api/handler.py` — Mangum adapter (Lambda entrypoint)
3. New CDK stack: `infra/lib/api-stack.ts` creating four tables
   (oauth-state with TTL, oauth-tokens with CMK, practices, plus
   IAM-grant on the existing phone_routing), the Python Lambda + Function
   URL, and the IAM surface (RW on tables, encrypt/decrypt on the
   tokens CMK, `connect:Search/ClaimPhoneNumber`,
   `secretsmanager:GetSecretValue` on the per-env PF client secret ARN).
4. ADRs + architecture doc + this session log.

### Sequencing in the callback (deliberate)

`/oauth/callback` writes `practices` + `oauth-tokens` *before* the DID
claim. Rationale: if `claim_phone_number` throttles (AWS limit ≈1-2
RPS), the tokens are already durable and the next attempt finishes
the missing DID claim without a second PF SMART round-trip. The state
row is consumed before either persistence step so a concurrent replay
of the same callback gets 400 immediately.

### Test surface

- `api/tests/test_oauth_callback.py` — 3 tests: happy path (writes
  all four rows + returns the DID), unknown state → 400, replay of
  consumed state → 400 + no double-claim
- `api/tests/test_oauth_start.py` — 1 test: 302 with PKCE/state params
  in the URL; state row persisted
- `api/tests/test_integration_onboarding.py` — headless code-exchange
  check, gated by `PF_AUTH_CODE_*` env vars. Kept around for the rare
  case where someone captures a fresh code by hand, but superseded as
  the **canonical integration test** by the Layer 3 Playwright spec
  described below.
- `web/tests/e2e/oauth_onboarding.spec.ts` — **the real integration
  test.** Drives the full SMART authorization-code grant against PF QA
  through a headless browser: hits `/oauth/start`, follows the redirect
  to PF, fills `PF_QA_USERNAME` / `PF_QA_PASSWORD`, enters the
  hardcoded QA 2FA code `12345`, clicks consent, lands back on
  `/oauth/callback`, asserts the response shape. Skipped when those
  env vars are absent so the unauthenticated CI lane stays green.
- `oauth/tests/test_state_store.py` — 6 tests
- `oauth/tests/test_code_exchange.py` — 4 tests
- `oauth/tests/test_practices_store.py` — +2 tests for the new `put`
- `routing/tests/test_connect_provisioner.py` — 5 tests
- `infra/test/api-stack.test.ts` — 6 jest tests

### CDK

- `infra/lib/api-stack.ts` (new) — described above
- `infra/bin/app.ts` — wires `ApiStack` with the connect instance
  ID/ARN passed through from `ConnectStack`, and the PF client secret
  ARN read from CDK context / env (`CDK_PF_CLIENT_SECRET_ARN`) with
  an env-prefixed default so synth stays green without it
- `cdk synth --context env=qa` produces 6 stacks clean (was 5):
  `pf-voice-qa-{audit, rate-limit, phone-routing, connect,
  agent-gateway, api}`

### Result

- `make test-ci` green across all four layers.
- Python: 138 tests (was 117, +21 — see breakdown above).
- Jest: 31 tests (was 25, +6 from `api-stack.test.ts`).

## Decisions made

- **ADR-0015** — FastAPI on Lambda behind a Function URL for the
  onboarding API. Rationale: two unauthenticated GETs, no
  request-mapping needs, Function URL is GA + HIPAA-eligible, API
  Gateway carries cost for none of the value at this surface. Future
  authenticated dashboard routes will get their own API Gateway
  (REST + Cognito); leaving onboarding on Function URL keeps that
  auth edge small.
- **ADR-0016** — `oauth-state` DDB table with TTL as the
  single-use PKCE/state cache; one PF Provider App per environment
  rather than per practice. The `practices_store` row still carries
  `pf_client_id` + `pf_client_secret_arn` per row so the schema
  accommodates future fan-out.
- **Persist tokens before claiming the DID** (no ADR — operational
  rule, captured in ADR-0015's consequences). Token persistence
  survives a throttled DID claim and avoids re-doing the SMART
  round-trip on retry.
- **Practices_store.put is idempotent overwrite** (no ADR — a re-
  onboarding of the same practice should land cleanly; tested).
- **Throttling is a typed error** (no ADR — implemented in
  `PhoneProvisionerThrottled`). The API layer can surface it as 503 +
  Retry-After once bulk onboarding lands in a later session.

## Open questions

1. **Lambda packaging.** `lambda.Code.fromAsset` currently ships only
   `api/src` — dependencies (fastapi, mangum, requests, oauth,
   routing) need a `pip install -t build/` pre-step before the first
   real deploy. Synth + unit tests don't notice; the deploy script
   does. Tracked for the deploy session.
2. **Redirect URI bootstrapping.** The Function URL only materializes
   at deploy time, so `OAUTH_REDIRECT_URI` is shipped empty in the
   CDK env block. First real deploy needs a follow-up to populate it
   (or to put a CloudFront alias in front).
3. **PF Provider App registration.** Needs an out-of-band human step
   per env to register the app with PF and stash the secret in
   Secrets Manager at the ARN ApiStack expects. CDK context var
   `pfClientSecretArn` overrides the default.
4. **End-to-end against real PF.** The integration test exercises only
   the headless code-exchange leg. A full UX walkthrough — operator
   clicks an onboarding link, completes PF's consent UI, lands back
   at the deployed Function URL — is a manual smoke test gated on
   the deploy + redirect URI being live.

## Next session pickup

**The first thing the next session should do:**

1. Read this file.
2. Read ADR-0015 + ADR-0016.
3. Run baseline:
   ```sh
   make test-ci      # 138 Python + 31 jest + ui-e2e + agent-e2e
   cd infra && npx cdk synth --context env=qa   # all 6 stacks clean
   ```
4. Skim `docs/roadmap.md` Session 0009 entry — note the pre-pivot
   prose warning; the direction (Connect AI agent prompt + the
   Patient.read enrichment for `lookup_patient`) is correct.

**Goal for Session 0009 (per pivoted plan):** Wire the Connect native
AI agent. (a) Author the verification system prompt (ADR-0013) in
`agent/prompts/verification.md` and provision it via
`AwsCustomResource` against the Connect AI-agent admin API. (b)
Replace the AI-agent stub block in `ConnectStack`'s contact flow with
the real `InvokeAgent` block. (c) Add the per-candidate `Patient.read`
fan-out to `lookup_patient` so the agent gets
`{name_first, name_last, date_of_birth, phone_masked}` per candidate
(Session 0007 OQ #3).

**First failing test for Session 0009:**
`tools/lookup_patient/tests/test_handler.py::candidates_carry_enrichment_fields`.

**Exit criteria for Session 0009:**
- `lookup_patient` returns enriched candidates; unit tests + tool
  schema updated to match.
- Connect AI agent provisioned with the verification prompt; contact
  flow handoff is the real `InvokeAgent` block rather than a stub.
- `make test-ci` green.

**Prerequisite blocks before opening 0009:**
- Confirm `AWS::Connect::AIAgent` CFN coverage as of 2026-05-23 (Session
  0007 OQ #1). If still uncovered, plan on `AwsCustomResource`.
- A first deploy of `pf-voice-qa-{audit, rate-limit, phone-routing,
  connect, agent-gateway, api}` is helpful for capturing real
  ARNs/IDs the AI-agent provisioning needs.

## Files changed

- `oauth/src/oauth/state_store.py` (new)
- `oauth/src/oauth/code_exchange.py` (new)
- `oauth/src/oauth/practices_store.py` — `put()` added
- `oauth/tests/test_state_store.py` (new, 6 tests)
- `oauth/tests/test_code_exchange.py` (new, 4 tests)
- `oauth/tests/test_practices_store.py` — +2 tests
- `routing/src/routing/connect_provisioner.py` (new)
- `routing/tests/test_connect_provisioner.py` (new, 5 tests)
- `api/pyproject.toml` — added oauth + routing as deps, moto + responses
  + integration marker as dev deps
- `api/src/api/onboarding.py` (new)
- `api/src/api/app.py` — DI-aware `build_app`, env-driven prod deps
- `api/src/api/handler.py` (new — Mangum adapter)
- `api/tests/test_oauth_callback.py` (new, 3 tests)
- `api/tests/test_oauth_start.py` (new, 1 test)
- `api/tests/test_integration_onboarding.py` (new, gated; superseded
  by the Playwright spec below as the canonical integration test)
- `ci/pyproject.toml` — added boto3, moto, fastapi, uvicorn, and the
  api / oauth / routing packages as runtime deps
- `ci/src/ci/local_onboarding_app.py` (new) — uvicorn factory that
  starts moto in-process, creates the four onboarding tables + KMS CMK
  + a fake PF client secret in moto Secrets Manager, stubs
  `ConnectProvisioner.claim_did`, and returns the real
  `api.app.build_app()` with the onboarding routes wired
- `ci/src/ci/start_local_stack.py` — `--onboarding` mode: port 8080
  (Veradigm-registered redirect URI), runs every spec under
  `web/tests/e2e/`
- `web/tests/e2e/oauth_onboarding.spec.ts` (new) — Playwright spec
  driving the real SMART code grant against PF QA
- `Makefile` — `test-ci-ui` now invokes `ci.start_local_stack
  --onboarding`
- `.env.example` — documents `PF_QA_USERNAME` + `PF_QA_PASSWORD`; 2FA
  is hardcoded `12345` in QA
- `infra/lib/api-stack.ts` (new)
- `infra/test/api-stack.test.ts` (new, 6 jest tests)
- `infra/bin/app.ts` — wires `ApiStack`
- `docs/decisions/0015-oauth-onboarding-fastapi-on-lambda.md` (new)
- `docs/decisions/0016-oauth-state-cache-and-single-pf-app.md` (new)
- `docs/architecture.md` — component map updated with `oauth-state`
  table + the onboarding API surface
- `docs/sessions/0008-oauth-onboarding-api.md` (this file)

## Notes for future Claude

- **`OAuthStateStore.consume` is the single-use guard, not a wrapper.**
  It's a DDB `DeleteItem` with `ReturnValues=ALL_OLD` — atomic
  delete-and-return. Don't refactor it into a get + delete; the race
  window between those two calls is exactly the replay surface this
  store exists to close.
- **Token persistence happens *before* the DID claim.** A throttled
  DID claim must not lose the tokens. If you ever reorder these,
  add a test that simulates `PhoneProvisionerThrottled` mid-callback
  and asserts the tokens survived.
- **`PhoneProvisionerThrottled` is the typed signal the API layer
  watches for.** Don't swallow it into the generic
  `PhoneProvisionerError`. Bulk onboarding (a later session) chunks
  on this exception.
- **Function URL has no concrete URL at synth time.** The CDK env
  block ships `OAUTH_REDIRECT_URI=""` deliberately — the first deploy
  populates it (or a CloudFront alias does). Don't add a synth-time
  expression that tries to invent the URL — the Function URL CFN
  return value is a token, and embedding it in env vars makes the
  Lambda's own deployment cyclical.
- **`api.app.build_app()` returns a healthz-only app when the env
  vars aren't wired.** The CI UI-E2E harness (Session 0005's
  `start_local_stack --healthz-only`) depends on this behavior. Don't
  switch to a hard failure on missing env vars — the local stack and
  the deployed Lambda use the same factory.
- **Pre-existing stubs left in place.** `oauth/src/oauth/routes.py`
  and `oauth/tests/test_callback.py` are pre-pivot placeholders
  (`build_app` raises `NotImplementedError`) — the real OAuth routes
  now live in `api.onboarding`. The stubs are harmless but stale.
  Auto-mode declined to delete them this session; they remain as a
  passing placeholder until a future session can remove them with
  the user's explicit OK.
- **The real integration test is the Playwright spec, not the gated
  pytest file.** `web/tests/e2e/oauth_onboarding.spec.ts` drives the
  full SMART code grant against PF QA. The harness boots the API on
  port 8080 — that's not a free choice, it's the redirect URI
  Veradigm has registered for our Provider App (see `.env.example`
  and `docs/credentials.md`). If you ever change the port, you also
  have to re-register with Veradigm. PF QA 2FA is hardcoded `12345`
  for the test user; the harness stubs out the Connect DID claim so
  we don't pay ~$1 per CI run. `make test-ci-ui` runs this in
  `--onboarding` mode; it self-skips when `PF_QA_USERNAME` /
  `PF_QA_PASSWORD` aren't set.
- **`ci.local_onboarding_app` starts moto in the same process as
  uvicorn.** That's the only way for the FastAPI app's boto3 clients
  to see the mocked tables — moto's `mock_aws()` patches via the
  current process's botocore session. Don't refactor it to a separate
  `moto_server` subprocess unless you also swap the stores over to
  pointing at the mock server's endpoint URL.
- **One PF Provider App per env** (ADR-0016). The `practices_store`
  row schema still has `pf_client_id` + `pf_client_secret_arn`
  columns — they happen to be identical across rows in v1. If a
  future security review demands per-practice apps, fan the column
  out; nothing in the code path assumes the values are shared.
