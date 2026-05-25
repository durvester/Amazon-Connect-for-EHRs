# Session 0005 — CI pipeline + no-human-in-loop E2E test harness

**Date:** 2026-05-23
**Goal (one sentence):** Stand up `make test-ci` — the four-layer
(unit / svc-integration / ui-e2e / agent-e2e) harness — locally and in
GitHub Actions, so every session from 0006 onward can end on a green
single-command gate (Principle #2).

## What was done

- **Created the `ci/` package** with the four-layer harness:
  - `ci/src/ci/__init__.py` exposes `LAYER_MARKERS`
    (`unit`, `svc-integration`, `ui-e2e`, `agent-e2e`) — the source of
    truth that the harness self-check parses.
  - `ci/src/ci/mint_access_token.py` — at run-start, decrypts the
    sealed-box refresh-token fixture, calls
    `oauth.refresh.refresh_access_token` against PF QA, prints
    `PF_*=…` lines for the Makefile to source. Two modes:
    `--skip-if-no-fixture` (probe-only, returns 0 even on missing
    fixture; used by the unit layer) and `--export-env` (writes the
    env block; used by svc-integration).
  - `ci/src/ci/start_local_stack.py` — runs the FastAPI app via
    `uvicorn api.app:build_app --factory` on a free port, waits for
    `/healthz`, then runs Playwright if installed.
  - `ci/src/ci/run_synthetic_call.py` — imports
    `agent.local_invoke.invoke_synthetic` and asserts it returns
    `"ok"` (placeholder; Session 0010 replaces with real Connect
    `ContactEvent` playback).
- **Wrote the meta-test first** (`ci/tests/test_harness_self_check.py`
  `::test_test_ci_invokes_all_four_layers`). It runs `make -n test-ci`
  and asserts all four `::ci-layer::<name>` markers appear in the
  recipe. Failed before the Makefile target existed; passes now.
- **Added the four `test-ci-*` Makefile targets** plus a parent
  `test-ci` that chains them. Each layer's first command is
  `echo ::ci-layer::<name>` so `make -n` emits the marker line. The
  unit layer's `npm ci` falls back to `npm install` when
  `package-lock.json` is absent (it is, in 0005 — committing the
  lockfile is a Session-0006-or-later cleanup).
- **Built the sealed-box dev fixture path:**
  - `scripts/seed-dev-refresh-token.py` — encrypts
    `secrets/pf-qa-tokens.json` (gitignored, populated by
    `make spike-fhir`) into `secrets/pf-qa-refresh-token.enc` using
    PyNaCl sealed-box. First run generates a fresh keypair, writes the
    public key to `secrets/dev-fixture-pubkey.b64`, and prints the
    private key once (saved to `PF_DEV_FIXTURE_PRIVKEY` locally and as
    a GitHub Actions secret).
  - `ci/src/ci/_fixture.py` — shared decrypt helper; raises
    `FixtureUnavailable` if the ciphertext, pubkey, or
    `PF_DEV_FIXTURE_PRIVKEY` env var is missing. The harness handles
    this cleanly (svc-integration prints a warning and skips; the
    other three layers don't depend on it).
  - `.gitignore` carve-outs added so the ciphertext + pubkey can be
    committed alongside the still-gitignored `pf-qa-tokens.json`.
- **Wired `/healthz` into the real FastAPI app** — `api.app.build_app`
  now returns a working `FastAPI()` with the existing
  `api.routes.health.health` callable mounted at `/healthz`. Session
  0008 extends this factory; the slot is real now. Added
  `api/tests/test_app.py` as the smoke test.
- **Added `agent/src/agent/local_invoke.py`** — minimal
  `invoke_synthetic() -> "ok"` placeholder so the agent-e2e harness
  slot is real. Session 0010 replaces this. Added
  `agent/tests/test_local_invoke.py`.
- **UI-E2E plumbing:** `web/playwright.config.ts` reads
  `PLAYWRIGHT_BASE_URL` from the env set by `start_local_stack.py`;
  `web/tests/e2e/healthz.spec.ts` asserts `GET /healthz → 200 {status:
  ok}`. Excluded `tests/e2e/**` from vitest in `web/vite.config.ts`
  (vitest was trying to transform the Playwright spec and choking on
  the `@playwright/test` import).
- **`uvicorn>=0.30` added to `api`'s dev-deps** — strictly a dev/CI
  dependency; production Lambda still uses Mangum.
- **Replaced `.github/workflows/ci.yml`** with two jobs: `lint`
  (`make lint`) and `test-ci` (`make test-ci`). The test-ci job
  installs Playwright + Chromium with `--with-deps` (Linux-only flag,
  needed for CI's Ubuntu runner; the local Makefile drops
  `--with-deps`). `PF_DEV_FIXTURE_PRIVKEY` is read from
  repo-secrets-of-the-same-name.
- **Wrote `docs/runbooks/test-harness.md`** — what each layer is for,
  how to decide where a new test goes, day-one fixture setup, the
  failure modes we hit this session and how the harness handles them.
- **End-of-session validation:** `make test-ci` runs all four layers
  green locally (no fixture present, so svc-integration skips
  gracefully with a printed warning; the other three pass including a
  real Playwright run against `http://127.0.0.1:<random>/healthz`).
  Baseline `make test` also still green: **88 passed, 6 skipped** (was
  84 + 6 at end of 0004; new tests are the `api.app` smoke +
  `agent.local_invoke` smoke + `ci` harness self-check, in two
  pytest invocations).

## Decisions made

- **Sealed-box (libsodium / PyNaCl) for the dev refresh-token
  ciphertext, not KMS** (no ADR — judgment call). User direction:
  "who cares - this is QA - for PROD we will use secrets manager."
  Production path is unchanged (`docs/architecture.md` already names
  Secrets Manager). Sealed-box lets us check in a ciphertext without
  any AWS dependency and gives the property we want (anyone with the
  public key can re-encrypt; only the private key in env / Actions
  secret can decrypt). If we ever want KMS for QA too, swap the
  decrypt helper in `_fixture.py` — call sites don't change.
- **The unit layer skips on missing fixture instead of failing**
  (no ADR — judgment call). Unit tests have no business depending on
  PF QA creds. `mint_access_token --skip-if-no-fixture` returns 0
  with a printed warning. If you forget to set
  `PF_DEV_FIXTURE_PRIVKEY` locally, you still get a green unit gate;
  only svc-integration tells you you've drifted.
- **`build_app()` is now a real factory returning a real app**, not a
  Session-0008-deferred `NotImplementedError`. (No ADR.) The harness
  needs to start a real ASGI process; deferring `build_app` until
  Session 0008 would have meant either a separate harness-only app
  factory (duplication) or starting *no* server (defeating the layer).
  Session 0008 adds OAuth routes to the same factory — additive
  change, not a rewrite.
- **Playwright run is best-effort, not mandatory, at the local
  layer** (no ADR — judgment call). If `web/node_modules/@playwright/test`
  is absent, `start_local_stack.py` still does the Python `/healthz`
  probe and returns 0 with a printed note. CI installs Playwright +
  Chromium unconditionally (`--with-deps` on Ubuntu). Rationale:
  every local dev shouldn't pay the ~120MB Chromium download just to
  run `make test-ci`.
- **Existing `.github/workflows/ci.yml` matrix replaced with a
  single `test-ci` job** (no ADR). The matrix per-package lint+test
  jobs are now redundant with `make test-ci`'s unit layer. Kept a
  separate `lint` job because `make test-ci-unit` doesn't run ruff —
  Session 0006 may roll lint into the unit layer; not worth the churn
  here.

## Open questions

1. **Should `make test-ci-unit` run `make lint`?** The lint pass is
   currently a separate Actions job. If a future session makes ruff
   findings block the harness, drop the lint job and add `make lint`
   to the unit layer. Defer until someone trips on it.
2. **`package-lock.json` commit.** Neither `web/` nor `infra/` has a
   committed lockfile, so the harness falls back to `npm install`
   on first run. Should be committed in 0006 to make CI deterministic.
3. **Playwright browser caching in Actions.** First run downloads
   Chromium (~30 s on the runner). `actions/cache` over
   `~/.cache/ms-playwright` is the standard fix — defer until CI
   timing matters.
4. **Fixture seeding is still a manual one-time step** — see runbook.
   The seed script prints the private key once on first run; user
   has to capture it and stash it in `PF_DEV_FIXTURE_PRIVKEY` + the
   GitHub Actions secret. No way to automate that without surrendering
   the security property. Documented in
   `docs/runbooks/test-harness.md`.

## Next session pickup

**The first thing the next session should do:**
1. Read this file (especially the "Decisions made" block — three
   conventions Session 0006 needs to respect: `--no-integration` is
   the unit-layer marker convention, the `@pytest.mark.integration`
   tag is how svc-integration finds tests, and `build_app()` is the
   real factory).
2. Read `docs/roadmap.md` Session 0006 entry — `lookup_patient`
   hardening (refresh wire-in, audit log, rate limit).
3. Run baseline:
   ```sh
   make test         # 88 passed, 6 skipped expected
   make test-ci      # all four layers green; svc-integration skips
                     # cleanly unless PF_DEV_FIXTURE_PRIVKEY is set
   ```
4. (Optional but recommended before opening 0006:) seed the dev
   fixture so the svc-integration layer is exercising real PF QA in
   your inner loop, not just CI:
   ```sh
   make seed-dev-token    # prints private key on first run
   export PF_DEV_FIXTURE_PRIVKEY=…
   make seed-dev-token    # writes secrets/pf-qa-refresh-token.enc
   gh secret set PF_DEV_FIXTURE_PRIVKEY -b "$PF_DEV_FIXTURE_PRIVKEY"
   ```

**Goal for Session 0006 (per roadmap):** `lookup_patient` hardening —
refresh wire-in, per-FHIR-call audit log, per-(practice, ANI) rate
limit. First failing test:
`tools/lookup_patient/tests/test_handler.py::test_emits_one_audit_record_per_fhir_probe`
(today writes zero audit records). New `audit/` package introduced.

**Exit criteria for Session 0006** (per roadmap):
- `_get_credentials` reads from `oauth.token_store`, refreshes on
  near-expiry.
- `fhir_client.search_patient` retries once on 401 after refresh.
- Audit recorder writes one S3 object per FHIR probe; PHI never
  appears in structured logs.
- `audit.rate_limit` gates every call; over-budget surfaces as
  `match: "rate_limited"`.
- `make test-ci` green (this is the gate that starts to bind).

## Files changed
- `ci/pyproject.toml`, `ci/src/ci/{__init__.py,_fixture.py,mint_access_token.py,start_local_stack.py,run_synthetic_call.py}`, `ci/tests/test_harness_self_check.py` — new package
- `scripts/seed-dev-refresh-token.py` — new
- `Makefile` — `test-ci` + four layer targets; `seed-dev-token` target; `ci` added to `PYTHON_PKGS`
- `.gitignore` — carve-outs for sealed-box ciphertext + pubkey
- `api/src/api/app.py` — `build_app` is a real factory, mounts `/healthz`
- `api/tests/test_app.py` — new
- `api/pyproject.toml` — adds `uvicorn>=0.30` to dev-deps
- `agent/src/agent/local_invoke.py` — new
- `agent/tests/test_local_invoke.py` — new
- `web/playwright.config.ts`, `web/tests/e2e/healthz.spec.ts` — new
- `web/vite.config.ts` — exclude `tests/e2e/**` from vitest
- `.github/workflows/ci.yml` — replaced matrix with lint + test-ci jobs
- `docs/runbooks/test-harness.md` — new

## Notes for future Claude
- **PyNaCl is 1.6.2 in the venv** (installed this session). The `ci`
  package declares it as a runtime dep — re-bootstrap if a fresh venv
  doesn't have it.
- **The sealed-box ciphertext is not on disk yet** in this commit —
  the seed script's first-run-prints-private-key behavior means a
  human (not Claude) has to capture the private key. Documented in
  the runbook. Until then, the svc-integration layer skips
  gracefully. The harness is fully green without it.
- **`start_local_stack.py` spawns uvicorn with `os.environ.copy()`**.
  An earlier attempt scrubbed the env to `PATH=/usr/bin:/bin:/usr/local/bin`
  to be portable; that broke node/npm discovery for the Playwright
  subprocess. Pass-through is cleaner.
- **macOS-only quirk in the Makefile:** `npx playwright install
  chromium` is called *without* `--with-deps` because that flag
  installs Linux system packages (apt-only). CI uses `--with-deps`
  because it's on Ubuntu. If you ever need browser deps installed on
  macOS, install them via brew, not Playwright's helper.
- **The `npm ci || npm install` fallback** is a one-session bandage.
  Commit both `web/package-lock.json` and `infra/package-lock.json`
  in Session 0006 (or whenever the npm-installed deps stabilize) and
  delete the fallback.
- **`build_app` change is the kind of thing a future session might
  trip on** — the stub used to say "Implement in Session 0008", and
  Session 0008's roadmap still says "real `/authorize`, `/callback`,
  `/refresh`". That's fine: 0008 *extends* the factory, doesn't
  re-introduce it. If Session 0008 author starts by re-stubbing
  `build_app`, point them at this session's "Decisions made" block.
- **The `oauth.refresh` import in `ci.mint_access_token` is by
  module path**, not by package install — `ci` doesn't depend on
  `pf-oauth-service`. Both packages are installed editable from the
  same venv at bootstrap, so the import works without a real
  dependency edge. Same pattern as the Session 0004
  `test_integration_refresh.py` `sys.path` munging — different
  technique, same rationale.
