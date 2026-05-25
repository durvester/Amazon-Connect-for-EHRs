# Session 0001 — Bootstrap the harness

**Date:** 2026-05-23
**Goal:** Create the repository scaffolding, documentation harness, ADRs, TDD seed tests, and CI so future sessions can pick up cold. No feature code.

## What was done

- Initialized git repository at `/Users/m858450/Documents/GitHub/Amazon Connect Health/`.
- **Hydrated `.env` with Practice Fusion QA credentials** for the pilot test practice (see `docs/credentials.md` for the variable list). `.env` is gitignored; `.env.example` documents the shape and is committed.
- Created the full directory tree per the approved plan (see `/Users/m858450/.claude/plans/i-want-you-to-synthetic-storm.md`).
- Wrote the four documentation anchors:
  - `docs/context.md` — business context, decisions to date
  - `docs/architecture.md` — current target architecture + data model + OAuth flow + security model
  - `docs/credentials.md` — every credential we'll hold, where it lives, what we need from the user
  - `docs/glossary.md` — terminology for FHIR / SMART / Connect / AgentCore
- Wrote five ADRs in `docs/decisions/`:
  - 0001 — Bedrock AgentCore over Lex (and over Connect Health)
  - 0002 — Nova Sonic over Transcribe+Polly
  - 0003 — SMART Provider App with user scopes (to be validated with Veradigm)
  - 0004 — Python + Strands SDK for the agent
  - 0005 — CDK TypeScript for infra
- Wrote `README.md`, `CLAUDE.md`, `Makefile`, `.gitignore`, `.editorconfig` at the repo root.
- Wrote `docs/sessions/SESSION_TEMPLATE.md` plus this file (Session 0001 handoff).
- Wrote `.github/workflows/ci.yml`.
- Scaffolded Python packages with `pyproject.toml` + TDD seed tests:
  - `agent/`, `tools/lookup_patient/`, `tools/complete_verification/`, `tools/escalate_to_human/`, `oauth/`, `api/`
- Scaffolded Node packages: `infra/` (CDK TypeScript), `web/` (Vite React TS).
- Verified Python scaffold imports cleanly via a smoke `pytest` run.

## Decisions made

- All five ADRs above are decisions of this session; see each file for context and consequences.
- Repo layout chosen as one mono-repo at `/Users/m858450/Documents/GitHub/Amazon Connect Health/`. Each subpackage is independently testable.
- Default OAuth scopes in code: `user/Patient.read openid fhirUser offline_access` — to be overridden once Veradigm confirms exact string. ADR-0003 captures this.

## Open questions (for Session 2 / the user)

1. ~~Exact `PF_SCOPES` string from Veradigm.~~ **Resolved** — 20-scope string captured in `.env`. Note `fhiruser` (lowercase, one word) not `fhirUser`; `launch` scope included though standalone-launch may not need it. We'll see what PF returns on the discovery endpoint.
2. Does Veradigm allow `user/` scope tokens to be used for unattended (phone-time) reads? **Still open** — to validate empirically in later sessions. ADR-0003 stands until contradicted.
3. ~~Does Veradigm allow `http://localhost:8080/oauth/callback`?~~ **Resolved — yes, registered.**
4. Phone + DOB for the two consenting QA test patients (Mohit Milind Durve, Ayesha Durve) — to be filled into `.env` before running the Session 0002 spike.
5. BAA status of AWS account `086514900943` — verify in AWS Artifact before Session 6.

## Next session pickup

**The first thing the next session (Session 0002) should do:**

1. Read this file (`docs/sessions/0001-bootstrap.md`).
2. Read `docs/context.md` and `docs/architecture.md` if you haven't.
3. Verify `.env` is populated (it was hydrated at end of Session 0001):
   - `cat .env` should show `PF_FHIR_BASE_URL`, `PF_CLIENT_ID`, `PF_CLIENT_SECRET`, `PF_SCOPES`, `PF_REDIRECT_URI` filled in. If missing, ask the user.
   - Confirm `PF_TEST_PATIENT_1_PHONE` / `_DOB` and `PF_TEST_PATIENT_2_PHONE` / `_DOB` have been added — these are needed to run the patient lookup at the end of the spike. The user must pull these from the PF QA console before the spike will fully succeed.
4. Goal for Session 0002 (one sentence): **Run a CLI script that completes the SMART-on-FHIR `authorization_code` + PKCE flow against the live Practice Fusion test endpoint and successfully retrieves one test patient by phone + DOB.**
5. Exit criteria for Session 0002:
   - `scripts/spike-fhir.py` exists and is fully tested
   - Unit tests in `oauth/tests/test_pkce.py` and `oauth/tests/test_well_known.py` pass
   - The script successfully retrieves at least one consenting test patient from PF
   - The live CapabilityStatement is committed to `docs/research/pf-capabilitystatement.json`
   - This session's handoff written as `docs/sessions/0002-fhir-spike.md` with the next-session pickup block

## Files changed (created)

- `README.md`, `CLAUDE.md`, `Makefile`, `.gitignore`, `.editorconfig`
- `docs/context.md`, `docs/architecture.md`, `docs/credentials.md`, `docs/glossary.md`
- `docs/decisions/0001-bedrock-agentcore-over-lex.md` through `0005-cdk-typescript-for-infra.md`
- `docs/sessions/SESSION_TEMPLATE.md`, `docs/sessions/0001-bootstrap.md`
- `.github/workflows/ci.yml`
- Per-package `pyproject.toml`, `README.md`, source files, and TDD seed tests under `agent/`, `tools/*/`, `oauth/`, `api/`
- `infra/package.json`, `infra/cdk.json`, `infra/tsconfig.json`, `infra/bin/app.ts`, `infra/lib/*.ts`, `infra/test/infra.test.ts`
- `web/package.json`, `web/vite.config.ts`, `web/src/*`, `web/tests/*`
- `scripts/README.md`

## Notes for future Claude

- The plan file referenced by the user is at `/Users/m858450/.claude/plans/i-want-you-to-synthetic-storm.md` — read it once at session start if you need the big picture.
- Memory under `/Users/m858450/.claude/projects/-Users-m858450-Documents-GitHub-Amazon-Connect-Health/memory/` has feedback memories about: (a) verify constraints with primary sources before planning, (b) no Lex use AgentCore, (c) session-handoff + TDD harness pattern, (d) project context for Practice Fusion phone problem. Reading those is optional but useful.
- The user prefers terse responses, short status updates while working, and to be redirected if a question is going wrong rather than asked many questions.
- TDD discipline: every Python module ships with a failing-first test in its `tests/` directory. The seed tests in this session are marked `pytest.skip` or assert `not_implemented` — replace as you implement.
- Don't deploy any AWS resources in Session 0002. That's Session 0007's job. Session 0002 is purely a local CLI spike.
