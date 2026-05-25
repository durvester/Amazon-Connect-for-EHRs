# `make test-ci` — four-layer test harness

**Owner:** the green-bar gate. Every session from 0006 onward ends on a green
`make test-ci` (per roadmap Principle #2). Adding new tests means choosing the
right layer; this doc tells you which.

## The four layers

| # | Layer              | Marker                    | What it runs                                                                                          | When to add a test here |
|---|--------------------|---------------------------|-------------------------------------------------------------------------------------------------------|--------------------------|
| 1 | unit               | `::ci-layer::unit`        | `pytest -m "not integration"` across all Python packages + `vitest --run` + `jest` (infra synth)      | Pure-function logic, schema validation, FastAPI handler tests with `TestClient`, React component tests with React Testing Library, CDK synth snapshot tests. **No network, no AWS, no PF.** Use `moto` for AWS — it's still layer 1. |
| 2 | svc-integration    | `::ci-layer::svc-integration` | `pytest -m integration` after `ci.mint_access_token` refreshes a PF QA access token from the sealed-box fixture | Anything that hits a real PF QA endpoint, or that needs a freshly-minted access token. Tagged with `@pytest.mark.integration` and reads `PF_*` env vars set by the harness. |
| 3 | ui-e2e             | `::ci-layer::ui-e2e`      | Starts FastAPI via `uvicorn api.app:build_app --factory`, probes `/healthz`, runs Playwright specs   | Browser-driven tests of real user flows. In 0005 only `healthz.spec.ts`; real specs land per-session from 0009 onward. **Do not put backend-only logic here** — it's slow and the failure modes are noisy. |
| 4 | agent-e2e          | `::ci-layer::agent-e2e`   | `ci.run_synthetic_call` invokes `agent.local_invoke.invoke_synthetic` (placeholder until Session 0010) | After Session 0010 lands: tests that feed a recorded Connect `ContactEvent` to the Strands agent locally and assert tool-call timelines. **Not the place** for unit tests of individual tools. |

The markers (`::ci-layer::<name>`) are how the meta-test
`ci/tests/test_harness_self_check.py` confirms `make -n test-ci` invokes all
four layers. Adding a layer means updating both `ci/src/ci/__init__.py`'s
`LAYER_MARKERS` and the Makefile recipe.

## Choosing the right layer (cheat sheet)

- **It's a pure function or small handler.** Layer 1, full stop.
- **It needs an AWS service.** Use `moto` and stay in Layer 1. Real AWS in CI
  is a smell at this stage.
- **It needs PF QA credentials.** Layer 2. Tag with `@pytest.mark.integration`.
  Read tokens from env vars set by the harness; never read from
  `secrets/pf-qa-tokens.json` directly.
- **It needs a browser.** Layer 3. Live in `web/tests/e2e/*.spec.ts`. The
  harness starts the local FastAPI app for you and sets `PLAYWRIGHT_BASE_URL`.
- **It needs to drive the agent end-to-end with a real Connect-shaped event.**
  Layer 4 (post-Session-0010). Today it's a placeholder.

## The dev fixture (Session 0004 refresh token, sealed-box-encrypted)

QA-only path. Production credentials live in AWS Secrets Manager (see
`docs/architecture.md`); this fixture exists so CI can run unattended without
a human OAuth flow.

- **Ciphertext:** `secrets/pf-qa-refresh-token.enc` (committed).
- **Public key:** `secrets/dev-fixture-pubkey.b64` (committed). Anyone can
  re-encrypt with `make seed-dev-token`.
- **Private key:** env var `PF_DEV_FIXTURE_PRIVKEY` (base64). In CI this is
  the repo secret of the same name. Locally, set it in your shell rc.

### Day-one setup (one-time)

```sh
make spike-fhir           # one-time PF OAuth flow, populates secrets/pf-qa-tokens.json
make seed-dev-token       # first run prints the new private key and exits — save it
export PF_DEV_FIXTURE_PRIVKEY=<paste the printed value>
make seed-dev-token       # second run encrypts → secrets/pf-qa-refresh-token.enc
gh secret set PF_DEV_FIXTURE_PRIVKEY < <(echo $PF_DEV_FIXTURE_PRIVKEY)
make test-ci              # all four layers green
```

### Rotating the refresh token

Per Session 0004 findings, PF QA does *not* rotate refresh tokens — the
original keeps working. If PF ever revokes it (long idle, key rotation on
their end), the `make test-ci-svc` layer will fail with `RefreshTokenError`.
Re-run `make spike-fhir` to mint a new one, then `make seed-dev-token` to
re-encrypt. The keypair stays the same.

## Local feedback loops

Running the full harness takes ~30 s plus first-run Playwright install (~2 min,
once). For tight inner loops:

```sh
make test                   # everything, no layer separation, no PF QA
make test-ci-unit           # all layer-1 tests only
make test-ci-ui             # local API + Playwright only
```

## Failure modes seen so far

- **`npm ci` fails with "missing package-lock.json"** — the harness falls back
  to `npm install` automatically. Commit the lockfile to fix permanently.
- **`vitest` picks up `tests/e2e/healthz.spec.ts`** — solved in 0005 by
  excluding `tests/e2e/**` in `web/vite.config.ts`. If you add another e2e
  spec, it lives under `tests/e2e/`.
- **`make test-ci-ui` exits 0 without running Playwright** — `web/node_modules/@playwright/test`
  is missing or browsers aren't installed. The Python `/healthz` probe still
  ran; you'd see `# start_local_stack: Playwright not installed; python /healthz probe only.`
  in the log. Run `cd web && npm install --save-dev @playwright/test && npx playwright install chromium`.
