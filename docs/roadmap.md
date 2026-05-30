# Roadmap

> Codebase cleanup complete. Architecture settled on
> Lex + Nova Sonic + code-hook Lambda calling Claude (ADR-0019).
> Forward plan below focuses on multi-practice scale-out.
>
> Sessions 0001-0016 are historical — they describe earlier
> directions that evolved during implementation. The **current forward
> plan starts at Session 0018** at the bottom of this file.

This is the forward-looking master plan. Session numbers below refer to
development milestones; this file describes what is *next* and *why in this order*.

Sessions 0001–0003 are history (see their session logs). The original Session
0003 log queued "Strands agent skeleton" as Session 0004. **This roadmap
reorders that.** The agent skeleton is now Session 0010. The reason: the
agent was scheduled to be built on top of a credential shim, a non-existent
audit log, and an unproven Connect ↔ AgentCore wiring. Building it in that
order means none of the agent work could be exercised end-to-end against PF
until much later, and the central ADR-0003 question (do user-scope refresh
tokens work for unattended reads?) would stay open.

## Principles binding every session below

1. **TDD is non-negotiable.** Every session below names the *first failing
   test* that opens it. No code is written before that test is committed
   and failing. (CLAUDE.md mandate.)
2. **No human in the loop after Session 0005.** Sessions 0004 and 0005
   together establish a persisted PF refresh-token fixture and a CI
   harness that exercises UI + service + agent automatically. From
   Session 0006 onward, every session ends with a green `make test-ci`
   run that includes Playwright UI E2E and a synthetic-Connect-event
   agent E2E. The only human-in-loop gate is the real-phone smoke test
   at the Connect spike (0008) and the pilot cutover.
3. **Every session ends with a *vertical slice* working.** UI changes
   ship with the service changes that back them and the agent changes
   that consume them. No "we'll wire it up in the next session." The
   CI gate fails if any layer regresses.
4. **Audit + refresh land before anything talks to PF in anger.** Every
   PHI read after Session 0006 writes an audit record; every FHIR call
   after Session 0006 transparently refreshes its access token.
5. **One ADR per architectural change.** If a session changes a
   documented design choice, it writes an ADR in the same commit.
6. **No PHI in logs, ever.** Per-session test fixtures include
   `caplog`-based negative assertions where the code touches PHI.
7. **Scope discipline.** v1 verifies + routes + three high-value
   read-only tools. Each new tool is gated server-side: it refuses to
   run unless `complete_verification(success=true)` has been recorded
   for the current call.

## Use-case scope after this roadmap

Three new tools are added beyond `lookup_patient`. Each was picked on
two criteria: (a) drives real inbound call volume at primary-care
practices, and (b) the agent can fully **resolve** the call (give a
definitive answer), not just route to a human faster.

| Use case | In v1? | Tool | FHIR scope used | Call-resolution shape |
|---|---|---|---|---|
| Caller identity verification | ✓ (Session 0003) | `lookup_patient` | `user/Patient.read` | Gate for everything below |
| **Lab / imaging result status** | ✓ (Session 0013) | `lab_result_status` | `user/DiagnosticReport.read` | "Your labs from 5/14 are complete, Dr. X has reviewed them, expect a call within 2 business days" *or* "Still pending, please call back after 5/30." Resolves call. |
| **Visit summary + care-plan recall** | ✓ (Session 0014) | `visit_summary` | `user/Encounter.read` + `user/CarePlan.read` | "At your visit with Dr. X on 5/14, the plan was: \[≤3 bullets from the active CarePlan\]." Resolves call. |
| **Document / form / referral-letter status** | ✓ (Session 0015) | `document_status` | `user/DocumentReference.read` | "Yes, your school physical form was sent to Lincoln Elementary on 5/20" *or* "Not yet — the doctor still needs to sign off." Resolves call. |
| Appointment lookup/scheduling | ✗ | — | not granted (`Appointment` / `Schedule` / `Slot`) | — |
| Refill request | ✗ | — | write op, not granted | — |
| Result interpretation / triage | ✗ | — | clinical judgment, scope creep | — |

Tools 0014 and 0015 each require a **30-minute data-quality spike**
against PF QA before their implementation session opens — to confirm
that PF actually populates `CarePlan` and `DocumentReference`
resources for real practices. EHR data quality on these two resources
varies; if PF's are sparse, the session goal degrades and we'd rather
know that before writing tests. The spikes are listed as prerequisites
on the relevant sessions below.

What was originally drafted (medications / allergies / last-visit
lookups) was rejected: those answer questions patients already know
the answer to and don't reduce call volume. They're cheap demos, not
business value.

---

## Session 0004 — Refresh-token flow + KMS-encrypted DDB token store

**Goal:** Implement the SMART refresh-token exchange and persistent
encrypted token storage, so any Lambda can call PF with a current
access token without provider re-login.

**Why now:** PF access tokens expire in 5 minutes (Session 0002 finding).
Without refresh, nothing built after this point can be exercised
end-to-end. Also validates ADR-0003's central open question against PF QA:
*does* a refresh-minted access token (issued hours/days after the
original grant, no clinician present) work for unattended `Patient.read`?

**First failing test:**
`oauth/tests/test_refresh.py::test_refreshes_access_token_against_mocked_pf`
— `oauth.refresh.refresh_access_token(refresh_token, ...) -> TokenSet` is
imported; module does not yet exist.

**Exit criteria:**
- `oauth.refresh.refresh_access_token` implemented; unit tests cover
  success, expired-refresh, invalid-client, network error.
- `oauth.token_store` implemented against `moto`-mocked DDB + KMS:
  `get_tokens(practice_id)` / `put_tokens(practice_id, …)` round-trip
  with envelope encryption (KMS Decrypt at read, KMS Encrypt at write).
  Ciphertext written to DDB is never the plaintext.
- Integration test (skipped unless `PF_REFRESH_TOKEN` env present): calls
  `refresh_access_token` against PF QA, then immediately exercises
  `lookup_patient.fhir_client.search_patient` with the minted token —
  must return the same Mohit Durve match as Session 0003.
- ADR-0007 written: "user-scope refresh tokens are accepted by PF for
  unattended reads" (or, if they aren't, the Backend Services pivot
  ADR replacing 0003).

**Files added/changed:**
- `oauth/src/oauth/refresh.py` (new)
- `oauth/src/oauth/token_store.py` (replaces the Session 0006-marked stub)
- `oauth/tests/test_refresh.py`, `oauth/tests/test_token_store.py` (new)
- `oauth/tests/test_integration_refresh.py` (new, `@pytest.mark.integration`)
- `secrets/pf-qa-refresh-token.enc` (new, KMS-encrypted, gitignored
  source; ciphertext committed). Created by running
  `scripts/seed-dev-refresh-token.py` once after a manual
  `make spike-fhir`. This fixture unblocks no-human-in-loop CI from
  Session 0005 onward.
- `scripts/seed-dev-refresh-token.py` (new): reads a fresh refresh
  token from a `make spike-fhir` run, encrypts under a dev KMS key
  (or, if running locally without KMS, a sealed-box keypair stored in
  1Password — documented in the script header).
- `docs/decisions/0007-user-scope-refresh-tokens-validated.md` (or the
  pivot ADR)
- `oauth/pyproject.toml` — add `moto[dynamodb,kms]>=5` as dev dep

**Open questions to resolve before opening the session:**
- PF refresh-token TTL — read from token response, document in the ADR.
- Whether PF rotates refresh tokens on use (single-use refresh) — the
  store must handle both rotating and non-rotating servers. If
  rotating, the dev-fixture refresh ciphertext is regenerated
  on every CI run and the writeback path needs an in-memory cache to
  avoid double-rotation under parallel test execution.

---

## Session 0005 — CI pipeline + no-human-in-loop E2E test harness

**Goal:** A single `make test-ci` command — runnable locally and in
GitHub Actions — exercises unit tests, service-integration tests,
UI E2E (Playwright), and a synthetic-Connect-event agent E2E. PF QA
calls are real, signed by an access token minted at run-start from
the persisted refresh token from Session 0004. No human-in-loop after
the one-time OAuth grant.

**Why now:** Every session from 0006 onward is required to end on a
green `make test-ci` (Principle #2). The harness has to exist before
that mandate kicks in. It's also a one-time investment — done right
in 0005, never paid for again.

**First failing test:**
`ci/tests/test_harness_self_check.py::test_test_ci_invokes_all_four_layers`
— a meta-test that asserts a `make test-ci --dry-run` invocation
emits the four expected layer markers (`unit`, `svc-integration`,
`ui-e2e`, `agent-e2e`). Module/script does not yet exist.

**Exit criteria:**
- `make test-ci` runs four layers and returns non-zero on any
  failure:
  1. **Unit** — existing pytest + vitest across all packages.
  2. **Service integration** — pytest with `moto` for AWS; PF QA calls
     authenticated by minting an access token from
     `secrets/pf-qa-refresh-token.enc` at start of run.
  3. **UI E2E** — Playwright (headless Chromium) drives `web/` against
     a local API+web stack started by the harness; covers any pages
     that exist. (In Session 0005 there is no dashboard yet — the
     test just asserts the harness *starts* the stack cleanly and
     hits `/healthz`. Real UI tests are added incrementally per
     session from 0009 onward.)
  4. **Agent E2E** — Strands local-invoke harness fires a recorded
     synthetic Connect `ContactEvent` payload at the agent runtime
     (after Session 0010 exists; placeholder/no-op until then) and
     asserts the tool-call timeline. Today (Session 0005) this layer
     just asserts the harness *can* invoke a Strands agent locally.
- `.github/workflows/ci.yml` runs `make test-ci` on every push;
  refresh-token ciphertext is decrypted via a GitHub Actions
  secret + KMS key (or repository-encrypted dev secret if KMS not
  yet provisioned).
- A "harness contract" doc at `docs/runbooks/test-harness.md`
  documents what each layer is responsible for and how to add new
  tests at the right layer (so future sessions don't add Playwright
  tests for backend logic, etc.).
- All pre-existing tests run under `make test-ci` and remain green.

**Files added/changed:**
- `Makefile` — add `test-ci` target wrapping the four layers
- `ci/` (new package) — harness scripts: `mint_access_token.py`,
  `start_local_stack.py`, `run_synthetic_call.py`
- `web/playwright.config.ts`, `web/tests/e2e/healthz.spec.ts` (new)
- `.github/workflows/ci.yml` (new)
- `docs/runbooks/test-harness.md` (new)
- `agent/src/agent/local_invoke.py` (new minimal Strands runner —
  replaced/extended by Session 0010)

**Open questions to resolve before opening the session:**
- GitHub Actions secret management — KMS key ARN for decrypting the
  refresh-token ciphertext. If KMS isn't provisioned yet, use a
  Sodium sealed-box keypair (private key in Actions secret); migrate
  to KMS in 0006 alongside `phi-key` / `oauth-key`.

---

## Session 0006 — `lookup_patient` hardening: refresh wire-in, audit log, rate limit

**Goal:** `lookup_patient` becomes production-shaped. It reads
credentials from the token store (refreshing on the way), writes one
HIPAA audit record per FHIR call, and gates every call through a
per-(practice, ANI) rate limit. The env-var shim from Session 0003
is deleted.

**Why now:** All three changes cross-cut the same handler seam, share
test scaffolding, and together they unlock real-PHI flow. Splitting
them across sessions wastes per-session set-up cost. The CI harness
from 0005 catches any regression in the same green-bar gate.

**First failing test:**
`tools/lookup_patient/tests/test_handler.py::test_emits_one_audit_record_per_fhir_probe`
— extends the existing handler tests; today `lookup_patient` writes
zero audit records. Test imports `audit.disclosure_log.record`, which
does not yet exist.

**Exit criteria (all of the following, gated by `make test-ci` green):**

*Refresh wire-in*
- `_get_credentials(practice_id)` reads from `oauth.token_store`. If
  the cached access token has < 60 s remaining, it refreshes via
  `oauth.refresh.refresh_access_token` and writes the new pair back
  before returning.
- `fhir_client.search_patient` catches a 401 once, refreshes, retries
  once, then raises `FhirClientError`. Unit tests cover the happy
  retry and the give-up path.
- `PF_ACCESS_TOKEN` / `PF_FHIR_BASE_URL` env-var support is **removed**.

*Audit log*
- New `audit/` package; `disclosure_log.record(...)` writes to an S3
  bucket (moto in tests). Schema: `practice_id`, `call_id`,
  `timestamp`, `tool`, `query_template` (format pattern, never the
  real phone value), `result_resource_ids`, `disclosed_fields`.
- `lookup_patient` invokes the recorder **once per FHIR call** (i.e.
  once per probe), not once per lookup. Test asserts
  `probes_tried == len(audit_records)`.
- Negative test: `caplog` asserts no PHI value (raw phone, DOB, name)
  appears in any structured log line emitted by the handler.

*Rate limit*
- New `audit.rate_limit.check_and_increment(practice_id, ani, max_per_day)`
  backed by DDB ConditionalUpdate. Default budget 100/day per (practice,
  ANI). Over-budget raises `RateLimitExceeded`; `lookup_patient`
  surfaces this as `match: "rate_limited"` so the agent can route to
  human without leaking that a lookup was *attempted*.
- CDK constructs added for the audit bucket (S3 Object Lock compliance
  mode + KMS-CMK + public-access-block) and the rate-limit DDB table.
  Synth snapshot in `infra/test/`. Deployment lands in Session 0007.

**Files added/changed:**
- `tools/lookup_patient/src/lookup_patient/handler.py`
- `tools/lookup_patient/src/lookup_patient/fhir_client.py`
- `tools/lookup_patient/tests/test_handler.py`,
  `tools/lookup_patient/tests/test_fhir_client.py`
- `tools/lookup_patient/tests/test_integration_pf.py` — re-wire to read
  from token store fixture
- `audit/pyproject.toml`, `audit/src/audit/disclosure_log.py`,
  `audit/src/audit/rate_limit.py`, `audit/tests/...` (new package)
- `Makefile` — add `audit` to `PYTHON_PKGS`
- `infra/lib/audit-stack.ts`, `infra/lib/rate-limit-stack.ts` (CDK
  synth-only this session)
- `docs/decisions/0008-audit-and-rate-limit-at-tool-boundary.md`

---

## Session 0007 — Pivot to Connect-native AI agent + AgentCore Gateway

**Goal (rewritten, 2026-05-23):** Lay down the IaC for the
post-pivot voice surface — Connect instance + contact flow that
resolves DID → practice_id via the new `phone_routing` table,
AgentCore Gateway with `lookup_patient` registered as the first MCP
tool, ADRs documenting the pivot, slim refactor of `lookup_patient` to
candidates-only return (ADR-0013). No real call yet; real call moves
to Session 0009 behind onboarding API.

**Why now:** Mid-session discovery of two findings forced the rewrite
(see ADR-0011): (1) AgentCore Runtime takes containers, not Lambdas;
(2) Connect's Nov-2025 native AI agent + Gateway pattern obsoletes the
KVS/Strands/Lex stack we had planned. Surfacing this in Session 0007
rather than later was the entire point of the spike.

**First failing test (already green at session end):**
`infra/test/connect-stack.test.ts::contact flow reads SystemEndpoint
and sets practice_id attribute` — asserts the contact-flow JSON uses
Connect's native `InvokeAWSService` DDB integration against
`phone-routing`, sets the `practice_id` attribute, then hands off to
the AI agent block (Session 0009 swaps the handoff-stub for the real
AI-agent invocation).

**Exit criteria (met at session end):**
- 5 CDK stacks synth clean under `--context env=qa` (audit, rate-limit,
  phone-routing, connect, agent-gateway).
- New `routing/` Python package (`phone_routing_store.py`) with
  claim/resolve/release + 9 moto-mocked unit tests.
- `lookup_patient` slim refactored (ADR-0013): returns
  `{status, candidates, probes_tried}`; all 10 unit tests green; rate-
  limit + audit + refresh + ADR-0006 PF quirk all preserved verbatim.
- `tools/lookup_patient/tool_schema.json` authored (AgentCore
  ToolSchema format — the contract between Gateway and the Lambda).
- ADR-0011 (pivot), ADR-0012 (MCP-via-Gateway), ADR-0013 (decision-in-
  prompt), ADR-0014 (per-practice DID + phone_routing) landed; ADR-0001,
  0004, 0010 marked Superseded.
- CLAUDE.md updated (no longer "Not Connect Health — Epic-only"; now
  "Not Connect Health prebuilt agents — PF not a named partner").
- `make test-ci` green across all four CI layers (Principle #2).

**Real call is NOT in this session's exit criteria.** It moves to
Session 0009, behind Session 0008's OAuth onboarding API which
provisions a real PF practice's tokens + claims a real DID.

**Files changed:**

- `infra/lib/{connect-stack,agent-gateway-stack,phone-routing-stack}.ts` (new)
- `infra/test/{connect-stack,agent-gateway-stack,phone-routing-stack}.test.ts` (new)
- `infra/bin/app.ts` — wires the three new stacks alongside the
  existing audit + rate-limit stacks
- `routing/{pyproject.toml,src/routing/__init__.py,src/routing/phone_routing_store.py,tests/test_phone_routing_store.py}` (new package)
- `Makefile` — `routing` added to `PYTHON_PKGS`
- `tools/lookup_patient/src/lookup_patient/handler.py` — slim refactor
  (ADR-0013): candidates-only return; event fields renamed
- `tools/lookup_patient/tests/test_handler.py` + `test_integration_handler.py` —
  updated for the slim return shape
- `tools/lookup_patient/tool_schema.json` (new, the MCP contract)
- `docs/decisions/0011-connect-native-ai-agent-pivot.md` (new)
- `docs/decisions/0012-tools-as-mcp-via-gateway.md` (new)
- `docs/decisions/0013-decision-logic-in-prompt.md` (new)
- `docs/decisions/0014-per-practice-did-phone-routing.md` (new)
- `docs/decisions/0001-bedrock-agentcore-over-lex.md` — marked Superseded
- `docs/decisions/0004-python-strands-sdk.md` — marked Superseded
- `docs/sessions/0007-pivot-to-connect-native.md` (new, replaces the
  in-progress 0007 log from earlier in the day)
- `CLAUDE.md` — Connect Health line revised
- *Deleted* (pre-pivot, never deployed):
  `infra/lib/connect-agentcore-stack.ts`, its test, the
  hello_world_handler, the connect-bootstrap runbook, ADR-0010.

**Open questions carried into Session 0008:**

- AWS account team confirmation that AgentCore Gateway's inherited
  HIPAA eligibility (via AgentCore parent service) is acceptable for
  PHI flows. Empirical: AWS HIPAA-eligible services page note covers
  it, but worth confirming with the account team before pilot
  (Session 0014).
- Connect AI agent prompt v1 (verification reasoning) — Session 0009
  authors it; ADR-0013 sets the policy.
- AgentCore Gateway 30 s tool-invocation timeout: `lookup_patient`
  p99 against PF QA needs measuring under realistic load (Session 0009
  is the first real-traffic opportunity).

---

## Session 0008 — OAuth onboarding API (FastAPI on Lambda)

**Goal:** Real `/authorize`, `/callback`, `/refresh` HTTP endpoints
replacing `scripts/spike-fhir.py` so a practice can be onboarded from
a browser without anyone running a Python script.

**Why now:** The pilot practice cannot run `spike-fhir.py` against
their prod PF account. The dashboard (Session 0009) needs these
endpoints to call. Token store and refresh from Sessions 0004/0005
are dependencies that are now in place.

**First failing test:**
`api/tests/test_oauth_routes.py::test_authorize_redirects_with_pkce_and_state`
— uses FastAPI `TestClient` to call `/authorize?practice_id=…` and
asserts a 302 to PF's authorization endpoint with `code_challenge`,
`state`, and the registered redirect URI.

**Exit criteria:**
- `api/src/api/oauth_routes.py` implements all three endpoints.
- State stored in DDB with TTL; CSRF-safe.
- `/callback` exchanges code → token pair, persists via
  `oauth.token_store`.
- `/refresh` exposed as an admin-only endpoint (Cognito JWT scope
  check) for manual re-mint during dev.
- Integration test (`@pytest.mark.integration`): walks
  `/authorize → user signs into PF QA in browser → /callback` and
  asserts a token row lands in the store.

**Files added/changed:**
- `api/src/api/oauth_routes.py`, `api/src/api/state_store.py` (new)
- `api/tests/test_oauth_routes.py`, `api/tests/test_state_store.py`
- `infra/lib/api-stack.ts` — API Gateway + Lambda for the FastAPI app
- `scripts/spike-fhir.py` — annotated as deprecated; kept for ad-hoc
  debugging only

---

## Session 0009 — Minimal practice dashboard (Cognito + "Connect PF" button)

**Goal:** A single React page where a practice provider signs in via
Cognito and clicks "Connect Practice Fusion" to kick off onboarding.

**Why now:** Pilot practice can't onboard without it. Bare-minimum UI;
no call-review screens yet.

**First failing test:**
`web/src/__tests__/ConnectButton.test.tsx::renders sign-in then
redirects to /authorize` — vitest + React Testing Library.

**Exit criteria:**
- Cognito user pool provisioned via CDK; one test user seeded.
- React app authenticates via Cognito, calls `/authorize`, handles
  the post-callback "you're connected" state by polling
  `/practices/{id}/status`.
- E2E test (Playwright optional; if added, gated under
  `make test-e2e`) walks sign-in → connect → connected.

**Files added/changed:**
- `web/src/pages/Connect.tsx`, `web/src/api/oauth.ts`, tests
- `api/src/api/practice_routes.py` — `GET /practices/{id}/status`
- `infra/lib/auth-stack.ts` — Cognito user pool
- `infra/lib/web-stack.ts` — S3 + CloudFront for the SPA

---

## Session 0010 — Strands agent skeleton + PHI-pre-verification gate

**Goal:** The agent loop runs locally, drives a scripted conversation
through `lookup_patient`, never reveals PHI before
`complete_verification(success=true)`.

**Why now:** All dependencies are now real — refresh, audit, telephony
spike, onboarding. The agent can be exercised end-to-end from the first
green test.

**First failing test:**
`agent/tests/test_verification_dialog.py::test_caller_provides_phone_and_dob_then_agent_calls_lookup_patient`
— scripted conversation; mock LLM responses; asserts that the agent
emits a `lookup_patient` tool call with the correct shape.

**Exit criteria:**
- `agent/src/agent/main.py` wires Strands + Claude Sonnet 4.6
  (configurable to Haiku 4.5) + the three tool stubs.
- System prompt explicitly forbids speaking PHI before verification;
  tests assert this by simulating a `lookup_patient` return of
  `match: single, patient_id: opaque-handle` and checking the agent
  does *not* speak the patient's name (which it doesn't have).
- **Tool surface hardened:** `lookup_patient` now returns an opaque
  `verification_handle` instead of the raw `patient_id`. Only
  `complete_verification` can exchange the handle for the real ID
  inside the trusted Lambda. Belt-and-suspenders against prompt-leak.
- Multiple-match flow: the agent re-prompts for ZIP, then calls
  `lookup_patient` with an extra `zip` arg; FHIR client side-filters
  on `Patient.address.postalCode` post-search (PF does not index ZIP
  in `telecom`-token search).
- ADR-0010: "tool returns opaque handles; verification is server-side."

**Files added/changed:**
- `agent/src/agent/main.py`, `agent/src/agent/prompts.py`,
  `agent/src/agent/tools.py`
- `agent/tests/test_verification_dialog.py` and friends
- `tools/lookup_patient/src/lookup_patient/handler.py` — opaque
  handle, ZIP filter
- `agent/src/agent/hello_world_handler.py` — deleted (was Session 0007)
- `docs/decisions/0010-opaque-verification-handle.md`
- `docs/architecture.md` — strike `ssn_last4` from
  `verification_factors`; document `{phone, dob, zip}` as the v1 set
  (SSN is not in PF FHIR Patient and there is no clean retrieval path)

**Open question to resolve before opening:**
- Confirm PF `Patient.address.postalCode` is populated on test
  patients (one-shot QA query; ~5 minutes).

---

## Session 0011 — `complete_verification` + `escalate_to_human` tools

**Goal:** Both side-effect tools implemented end-to-end; agent flow
reaches a real Connect `UpdateContactAttributes` call.

**First failing test:**
`tools/complete_verification/tests/test_handler.py::test_writes_verified_attributes_and_calls_table`
— moto-mocked Connect + DDB; asserts attributes set, `calls` row
written, audit-log record emitted.

**Exit criteria:**
- `complete_verification` exchanges the opaque handle for the real
  `patient_id`, writes `{verified=true, patient_id, escalate=false}`
  to Connect, writes the `calls` row, emits an audit-log record.
- `escalate_to_human` writes `{verified=false, escalate=true,
  reason}` to Connect, writes the `calls` row.
- Three-attempt failure counter lives in agent state; on third
  failure the agent calls `escalate_to_human`.

**Files added/changed:**
- `tools/complete_verification/src/...`, tests
- `tools/escalate_to_human/src/...`, tests
- `infra/lib/calls-stack.ts` — `calls` DDB table

---

## Session 0012 — End-to-end pilot dry run (test-tenant, no real patients)

**Goal:** Real call → real Connect → real AgentCore → real PF QA →
real verified outcome → human queue, with the two Durve test patients.

**Why now:** Before any read-only post-verification tools, prove the
core verification flow lands cleanly in production-shape infra.

**First failing test:**
`infra/test/e2e/test_verification_call.ts::full call survives
verification` — synthetic-call harness. Not pure unit; gated under
`make test-e2e`.

**Exit criteria:**
- A test caller dials the DID; agent verifies; Connect routes to a
  test queue; transcript + audio + audit-log + `calls` row all
  appear; no PHI in CloudWatch.
- Pilot-readiness checklist in `docs/runbooks/pilot-go-no-go.md` —
  green for all rows.

**Files added/changed:**
- `infra/test/e2e/...`
- `docs/runbooks/pilot-go-no-go.md`

---

## Session 0013 — Read-only tool: `lab_result_status`

**Goal:** Verified callers asking "are my lab results back?" get a
definitive status answer and the call ends.

**Why now:** Top-tier inbound call driver. First and most valuable
post-verification capability. Establishes the read-only-tool pattern
that 0014 and 0015 reuse.

**First failing test:**
`tools/lab_result_status/tests/test_fhir_client.py::test_returns_status_of_most_recent_diagnostic_report`
— mocked Bundle with two `DiagnosticReport`s (one `final`, one
`preliminary`); the tool returns the most-recent-by-`effectiveDateTime`
with its status, and never the actual result values.

**Exit criteria (all gated by `make test-ci` green):**
- New tool package `tools/lab_result_status/` mirroring the
  `lookup_patient` layout.
- FHIR call: `GET {base}/DiagnosticReport?patient={id}&_sort=-date&_count=5`.
  Five most recent reports; client picks the freshest and surfaces:
  `{report_date, category_text, status, ordering_practitioner_name}`.
  Never returns result codes, values, observations, or attachments.
- Status mapping for the agent: FHIR `final` / `amended` →
  `"complete, awaiting provider review or already reviewed"`; FHIR
  `preliminary` / `partial` / `registered` → `"in progress"`; FHIR
  `cancelled` / `entered-in-error` → `"unavailable, please speak with
  the office"`.
- Server-side verification gate: rejects unless the `calls` row for
  the current `call_id` shows `verification_outcome=verified`. Test
  asserts a fabricated handle from another call is rejected.
- Audit-log record per FHIR call.
- Integration test against PF QA: confirms response shape for a seeded
  `DiagnosticReport` against a Durve test patient. If PF QA has no
  DiagnosticReports for the Durves, the session's first action is a
  data-seeding step in the PF UI documented in
  `docs/runbooks/pf-qa-test-data.md`.
- Agent prompt extension recognizes "are my results back" / "did my
  bloodwork come in" / "lab results" and calls the tool.
- UI: dashboard "recent calls" view shows `lab_result_status` as a
  resolution outcome (no PHI — just the tool name + status string).
- Playwright E2E asserts the recent-calls view renders the new
  outcome label.

**Files added/changed:**
- `tools/lab_result_status/` (new, full TDD package)
- `agent/src/agent/prompts.py` — extend
- `agent/tests/test_post_verification_dialog.py` — new
- `web/src/pages/RecentCalls.tsx` — extend with new outcome label
- `web/tests/e2e/recent-calls.spec.ts` — extend
- `docs/runbooks/pf-qa-test-data.md` (new, if seeding required)

**Voice-readback rules (decided here, applies to 0014/0015 too):**
- Read at most one item by default. If multiple exist, summarize the
  freshest and offer "you also have N older results, would you like
  me to read those?" — never blast a list at the caller.

---

## Session 0014 — Read-only tool: `visit_summary`

**Goal:** Verified callers asking "what did the doctor tell me to do
after my last visit" get a brief read-back of the most recent active
care plan tied to their last Encounter.

**Why now:** Second-tier call driver, especially in the 24–72 hours
after a visit. Reuses the verification gate + audit + voice-readback
plumbing established in 0013.

**Prerequisite spike (≤30 minutes, done before the session opens, not
during):**
- Query PF QA: how many of the Durve test patients have any
  `CarePlan` resources? What's a typical payload size and content
  density? Findings recorded to `docs/research/pf-careplan-quality.md`.
- **Go/no-go gate:** if PF's `CarePlan` resources are empty stubs or
  not populated for most patients, this session is replaced with a
  fallback tool that reads the last `Encounter`'s `reasonCode` +
  `Practitioner` name only ("you saw Dr. X on 5/14 for a follow-up;
  please call the office for next-steps"). The fallback is honest
  about its limitations; building on hollow data is worse than
  saying so.

**First failing test:**
`tools/visit_summary/tests/test_fhir_client.py::test_returns_most_recent_active_careplan_with_encounter_context`
— mocked Bundle: one Encounter + one active CarePlan referencing it.
Tool returns `{encounter_date, practitioner_name, plan_summary_lines:
list[str]}` with at most 3 lines.

**Exit criteria (all gated by `make test-ci` green):**
- New tool package `tools/visit_summary/` mirroring the established
  shape.
- FHIR calls (chained):
  1. `GET {base}/Encounter?patient={id}&_sort=-date&_count=1`
  2. `GET {base}/CarePlan?patient={id}&status=active&_sort=-date&_count=1`
- Returns a voice-friendly summary, at most 3 bullet points from
  `CarePlan.activity.detail.description` or `CarePlan.description`.
- Verification gate, audit-log records (one per FHIR call), prompt
  recognition for "what did the doctor say" / "my care plan" / "after
  visit instructions".
- UI: dashboard outcome label + Playwright assertion.

**Files added/changed:**
- `tools/visit_summary/` (new)
- `agent/src/agent/prompts.py`, `agent/tests/...`
- `web/src/pages/RecentCalls.tsx`, `web/tests/e2e/recent-calls.spec.ts`
- `docs/research/pf-careplan-quality.md` (from prerequisite spike)

---

## Session 0015 — Read-only tool: `document_status`

**Goal:** Verified callers asking "did Dr. X send my school physical
to the school" / "is my disability form ready" get a definitive
yes-and-when or no answer.

**Why now:** Third-tier call driver; forms / referrals / signed
letters are a steady source of front-desk interruption. Same scaffold
as 0013/0014.

**Prerequisite spike (≤30 minutes, before the session opens):**
- Query PF QA: are `DocumentReference` resources populated for the
  Durve test patients? What `category` / `type` codings does PF use
  for patient-facing artifacts vs. clinical notes? Findings to
  `docs/research/pf-documentreference-quality.md`.
- **Go/no-go gate:** if PF only exposes clinical-note
  DocumentReferences (not patient-facing forms), the session goal
  narrows to "tell the caller a document of type X exists, dated Y,
  please call the office to receive a copy" — still useful but more
  limited. If even that isn't there, swap this session for a second
  pilot-cutover-prep session.

**First failing test:**
`tools/document_status/tests/test_fhir_client.py::test_returns_most_recent_document_matching_category_filter`
— mocked Bundle with three DocumentReferences across two categories;
tool returns the most-recent in the requested category and never
returns the binary content.

**Exit criteria (all gated by `make test-ci` green):**
- New tool package `tools/document_status/`.
- FHIR call:
  `GET {base}/DocumentReference?patient={id}&category={cat}&_sort=-date&_count=3`.
- Returns `{document_type, status, date_authored, recipient_name_if_set}`.
  **Never returns the document content or attachment URL.**
- Agent prompt: extracts a "what kind of document" cue from the
  caller ("school physical" → school-physical category, "disability"
  → disability-form category, etc.), maps to PF's `type` codings via
  a small lookup table validated against the spike findings.
- Verification gate, audit-log record per FHIR call, UI outcome label,
  Playwright assertion.

**Files added/changed:**
- `tools/document_status/` (new)
- `agent/src/agent/prompts.py`, `agent/tests/...`
- `web/src/pages/RecentCalls.tsx`, `web/tests/e2e/recent-calls.spec.ts`
- `docs/research/pf-documentreference-quality.md` (from spike)

---

## Session 0016 — Pilot cutover prep

**Goal:** Everything needed to point a real practice at this system,
short of the practice clicking the button.

**Exit criteria:**
- Practice onboarding runbook in `docs/runbooks/practice-onboarding.md`.
- Per-practice config table populated for the pilot practice in CDK.
- Token-refresh-failure alarm in CloudWatch → SNS → on-call.
- Rate-limit hit alarm.
- Audit-log access-policy review (only the compliance role can read).
- All `@pytest.mark.integration` tests green against PF QA on a
  fresh-CI run.
- ADR-0011: "Pilot go-live readiness — what we accepted and what we
  deferred."

---

## How to start when this redraft is final

```bash
cd "/Users/m858450/Documents/GitHub/Amazon Connect Health"
make test                       # baseline: 66 passed, 5 skipped
$EDITOR docs/roadmap.md         # re-read this file, especially Session 0004
$EDITOR docs/sessions/0003-lookup-patient-lambda.md   # pickup block points here
```

The first step into Session 0004 is the named first-failing test on
the Session 0004 entry. No code or tests are written before that
failing test is committed (TDD invariant).

By the end of Session 0005, `make test-ci` exists and is the
universal gate for every session thereafter. Sessions 0006–0016 each
end with that command green, exercising unit + service-integration +
UI (Playwright) + agent (synthetic Connect event) without any human
in the loop. The only human-required gates are: (a) the one-time
`make spike-fhir` to seed the PF refresh-token fixture in Session
0004, (b) the real-phone smoke test at the end of Session 0008, and
(c) the real-phone smoke test at the end of Session 0012 (E2E pilot
dry run) and Session 0016 (pilot cutover).

---

## What this roadmap explicitly does **not** do

These remain out of v1, listed so that scope creep is rejected by name:

- Appointment scheduling or lookup (no `Appointment` scope from PF).
- Refill *requests* — would require `MedicationRequest.write`.
- Clinical Q&A or symptom triage.
- EHR write-back of any kind.
- Multi-practice self-service onboarding portal (manual onboarding via
  runbook is fine for the pilot).
- Multi-language. Non-English callers escalate to a human.
- Number-portability fallback — if PF has a stale phone for the
  patient, verification fails and the call escalates. Acceptable for
  v1; the pilot practice should be told.

## Open questions to surface with Veradigm before Session 0008

These are commercial / partnership questions and not technically
blocking earlier sessions, but the answers shape Sessions 0008+:

1. Per-app PF API rate limits (concurrent + daily).
2. Refresh-token TTL and whether refresh tokens are rotated on use.
3. Production-tenant onboarding process — is there a sandbox-to-prod
   promotion path or do practices use a separate prod client_id?
4. Provider-offboarding behavior — does PF invalidate refresh tokens
   when the granting clinician leaves the practice? If so, what's the
   detection signal we get?

---

## Forward Plan: Multi-Practice Scale-Out (Session 0018+)

### Current State (Session 0017)

One pilot practice live on +16156250631. Architecture is multi-tenant by design:
- `pf_org_uuid` is the practice key everywhere (ADR-0020)
- `phone_routing` table maps DID → practice at every call
- `practices` + `oauth-tokens` tables are per-practice
- OAuth onboarding (`/oauth/start` → `/oauth/callback`) provisions end-to-end
- PF auth scales inherently — each practice authorizes the Provider App once, gets their own KMS-encrypted refresh token

### The Practice Signup Journey (target)

```
Practice admin visits dashboard
  → Signs in (Cognito)
  → Clicks "Connect Practice Fusion"
  → Redirected to PF OAuth (authorization_code + PKCE)
  → Grants user/Patient.read + offline_access
  → Callback writes: practices row, KMS-encrypted tokens, claims DID, writes phone_routing
  → Practice sees: "Your verification line is +1-XXX-XXX-XXXX"
  → Practice configures call forwarding (or publishes the DID directly)
  → Calls flow immediately
```

### Scale-Out Jobs-To-Be-Done

**S1: "Let me sign up my practice in under 5 minutes"**
- Cognito user pool + hosted UI for practice staff auth
- Dashboard (React app in `web/`): onboarding wizard, call history, settings
- Backend API: implement calls list + practice config routes
- Auth middleware: Cognito JWT verification

**S2: "Give me a phone number patients can call"**
- Number selection: area code picker via `SearchAvailablePhoneNumbersV2` `PhoneNumberPrefix`
- Number porting: `CreatePhoneNumberOrder` for practices keeping their existing number
- DID inventory: pre-reserve pool for instant assignment at scale

**S3: "I want to see how calls are going"**
- Call history page from `calls` table (already populated by lex_code_hook)
- Metrics: verification success rate, call duration, escalation reasons

**S4: "Don't break my existing phone setup"**
- Call forwarding setup wizard (carrier-specific instructions)
- Business hours config per practice
- After-hours behavior: configurable message + disconnect vs voicemail

### How PF Auth Scales

No architectural changes needed:
1. One Provider App per environment (ADR-0016): all practices share one `client_id`/`client_secret`
2. Token refresh is per-practice, on-demand: `get_credentials(pf_org_uuid)` handles refresh
3. Invalid grant → reconnect: `InvalidGrantError` → `status=needs_reconnect` → dashboard shows reconnect
4. 20K practices = 20K rows in oauth-tokens: DynamoDB PAY_PER_REQUEST, single-digit ms

### Monetization

Recommended for pilot: monthly subscription ($99/mo) with 30-day free trial.
Alternative models: per-call ($0.10-0.25), freemium (free verification, paid JTBDs 2-4).

### Bulk Onboarding (20K practices)

DID claiming rate-limited at ~1-2 RPS. Strategies:
- SQS queue + Lambda consumer for async DID claiming
- Pre-reserve DID pool for instant assignment on signup

### Conversation Analytics Pipeline

Inspired by the [AWS contact center RAG solution](https://aws.amazon.com/blogs/machine-learning/deploy-generative-ai-agents-in-your-contact-center-for-voice-and-chat-using-amazon-connect-amazon-lex-and-amazon-bedrock-knowledge-bases/).

CloudWatch Logs → Amazon Data Firehose → S3 data lake → AWS Glue crawler → Amazon Athena.
Optional PII redaction via Amazon Comprehend in the Firehose transformation Lambda.
Amazon QuickSight dashboards for per-practice call volume, verification success rate,
escalation reasons, p95 turn latency, and tool usage patterns.

This replaces ad-hoc CloudWatch Logs Insights queries with a queryable, dashboardable data layer.

### Lambda Provisioned Concurrency

Add `provisionedConcurrency` to EnvConfig (0 for QA, configurable for prod).
Apply to the code-hook Lambda only (the latency-sensitive path).
A cold start adds 1-2 seconds to the first turn on a voice call; provisioned
concurrency eliminates this. The router Lambda is fast enough (<5ms) that cold
starts are negligible.

### Async Verification Confidence Check

After each call, the code-hook Lambda publishes a message to an SQS queue with
the call evidence: phone match result, DOB confirmation, patient resource ID,
tool calls made, and verification outcome. A second Lambda consumes the queue,
re-evaluates the evidence against the verification rules, and logs the result
to the audit bucket. This is adapted from the hallucination detection pattern
in the AWS contact center RAG solution but applied to verification correctness
rather than generated-text factuality.

### Implementation Priority

| Session | What | JTBD |
|---------|------|------|
| 0018 | Cognito user pool + auth middleware + dashboard skeleton | S1 |
| 0019 | Dashboard: onboarding wizard + call history page | S1, S3 |
| 0020 | Number selection UI (area code picker) | S2 |
| 0021 | Business hours config + after-hours behavior | S4 |
| 0022 | Number porting flow | S2 |
| 0023 | Billing integration (Stripe subscription) | Monetization |
| 0024 | Bulk onboarding (SQS queue + DID pool) | Scale |
| 0025 | Conversation analytics pipeline (Firehose → Glue → Athena → QuickSight) | S3, Ops |
| 0026 | Lambda provisioned concurrency (code-hook) | Perf |
| 0027 | Async verification confidence check (SQS → Lambda → audit) | Compliance |
