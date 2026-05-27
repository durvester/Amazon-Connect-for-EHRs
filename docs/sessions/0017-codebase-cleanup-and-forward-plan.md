# Session 0017 — Codebase cleanup and multi-practice forward plan

**Date:** 2026-05-27
**Goal (one sentence):** Prune all dead code from architectural pivots, fix IAM wildcards and a PHI-safety timebomb, and write the forward plan for multi-practice scale-out.

## What was done

### Dead code removal (Groups 1-3)
- Deleted `tools/complete_verification/` (NotImplementedError stub; logic inlined in lex_code_hook)
- Deleted `tools/agent_action_group/` (POC from Sessions 0015-0016, torn down)
- Deleted `agent/` package (Strands SDK stubs from Sessions 0001-0005)
- Deleted `oauth/routes.py` + `oauth/tests/test_callback.py` (replaced by api/onboarding.py)
- Deleted `api/auth.py`, `api/routes/calls.py`, `api/routes/practices.py` (unimplemented stubs)
- Removed `poc/` directory (git rm, was locally deleted but unstaged)
- Staged session docs 0015 and 0016
- Deleted stale forward-plan-revised.md and forward-plan-session-0014.md
- Updated CI `run_synthetic_call.py` to be self-contained after agent/ removal
- Fixed pre-existing ruff lint errors across 5 packages (unused imports, unused variables)

### Config and IaC cleanup (Groups 4-6)
- Simplified dead ternary in audit-stack.ts (`? false : false` → `false`)
- Consolidated duplicate `oauthKmsKeyArn`/`oauthKmsKeyArnForGrant` props in lex-stack.ts
- Removed dead `import requests` / `del requests` in ci/mint_access_token.py
- Parameterized hardcoded practice/patient IDs in probe-fhir-resources.py
- Scoped `bedrock:InvokeModel` from `*` to `anthropic.*` foundation model ARNs
- Scoped `secretsmanager:GetSecretValue` from all secrets to env-prefixed pattern
- Scoped `connect:ClaimPhoneNumber` from `*` to specific Connect instance ARN
- Removed `AgentGatewayStack` (dead infrastructure from Sessions 0007-0010)
- Updated architecture.md to reflect direct tool bundling (no Gateway)

### PHI-safety timebomb fix (Group 7)
- `_load_system_prompt()` previously fell back to a hardcoded 4-line prompt with NO PHI safeguards if the prompt file was missing from the Lambda bundle
- Now raises RuntimeError — the Lambda fails loud at cold start rather than silently degrading
- Added test to verify RuntimeError is raised when no prompt file exists

### CLAUDE.md update
- Added build/test/lint commands and package map

## Decisions made
- `practice_id` DDB column stays as-is (stores pf_org_uuid values, naming inconsistency deferred — rename requires table recreation)
- AgentGatewayStack removed (no ADR — it was dead infrastructure nobody consumed)
- System prompt fallback removed in favor of hard error (no ADR — PHI safety correctness)

## Open questions
1. Should the forward plan for multi-practice scale-out become an ADR or stay as session guidance?
2. When to reconcile CLI-deployed resources as CDK IaC? (Session 0016 pickup note)

## Next session pickup

**The first thing the next session should do:**
1. Read this file
2. Read `docs/architecture.md` and `docs/context.md`
3. The repo is clean and ready for remote push. Production system on +16156250631 works.
4. **Forward plan priority order:**
   - Session 0018: Cognito user pool + auth middleware + dashboard skeleton (JTBD S1)
   - Session 0019: Dashboard onboarding wizard + call history page (JTBD S1, S3)
   - Session 0020: Number selection UI with area code picker (JTBD S2)
   - Session 0021: Business hours config + after-hours behavior (JTBD S4)
   - Session 0022: Number porting flow (JTBD S2)
   - Session 0023: Billing integration (monetization)
   - Session 0024: Bulk onboarding with SQS queue + DID pool (scale)

**Key context for next session:**
- PF auth already scales: each practice authorizes the Provider App, gets their own refresh token, stored KMS-encrypted in oauth-tokens table. No architectural changes needed for multi-practice.
- The onboarding flow (/oauth/start → /oauth/callback) already provisions end-to-end: tokens + DID + routing. Dashboard + Cognito are the missing pieces.
- `api/auth.py` and `api/routes/{calls,practices}.py` were deleted as stubs — re-implement when the dashboard is built.
- DID claiming is rate-limited by AWS at ~1-2 RPS. For 20K practices, use SQS queue or pre-reserve a DID pool.

## Files changed
- `tools/complete_verification/` (deleted)
- `tools/agent_action_group/` (deleted)
- `agent/` (deleted)
- `oauth/src/oauth/routes.py` (deleted)
- `oauth/tests/test_callback.py` (deleted)
- `api/src/api/auth.py` (deleted)
- `api/src/api/routes/calls.py` (deleted)
- `api/src/api/routes/practices.py` (deleted)
- `poc/` (deleted)
- `infra/lib/agent-gateway-stack.ts` (deleted)
- `infra/test/agent-gateway-stack.test.ts` (deleted)
- `docs/sessions/forward-plan-revised.md` (deleted)
- `docs/sessions/forward-plan-session-0014.md` (deleted)
- `tools/lex_code_hook/src/lex_code_hook/handler.py` (prompt timebomb fix + lint fixes)
- `tools/lex_code_hook/tests/test_handler.py` (new test + lint fixes)
- `infra/lib/lex-stack.ts` (IAM scoping + prop consolidation)
- `infra/lib/api-stack.ts` (IAM scoping)
- `infra/lib/audit-stack.ts` (dead ternary fix)
- `infra/bin/app.ts` (removed AgentGatewayStack + duplicate prop)
- `infra/test/lex-stack.test.ts` (removed duplicate prop)
- `Makefile` (removed dead packages from PYTHON_PKGS)
- `ci/src/ci/run_synthetic_call.py` (self-contained after agent/ removal)
- `ci/src/ci/mint_access_token.py` (dead import removal)
- `scripts/probe-fhir-resources.py` (parameterized hardcoded IDs)
- `docs/architecture.md` (removed Gateway references)
- `CLAUDE.md` (added build/test/lint commands + package map)
- Multiple test files (pre-existing lint fixes)

## Notes for future Claude
- The `complete_verification` tool name still exists in lex_code_hook/handler.py as a tool_name string — it's the tool Claude calls, not an import. The logic is inline at handler.py:174-179.
- The `agent/` package was the Strands SDK stub. The actual agent logic is in `tools/lex_code_hook/` — the code-hook Lambda IS the agent brain.
- build/ directories exist on disk (setuptools artifacts) but are gitignored. They're harmless.
- `SearchAvailablePhoneNumbersV2` IAM resource is scoped to Connect instance ARN. If a second Connect instance is added, the policy needs updating.
- The Bedrock model IAM is scoped to `anthropic.*` and `us.anthropic.*` patterns. If switching to a non-Anthropic model, update lex-stack.ts.
