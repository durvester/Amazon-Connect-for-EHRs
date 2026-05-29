# Session 0017 — Codebase cleanup, deploy, and multi-practice forward plan

**Date:** 2026-05-27 to 2026-05-28
**Goal (one sentence):** Prune all dead code from architectural pivots, fix safety issues, deploy, push to remote Git, and write the forward plan for multi-practice scale-out.

## What was done

### Dead code removal
- Deleted `tools/complete_verification/` (NotImplementedError stub; logic inlined in lex_code_hook)
- Deleted `tools/agent_action_group/` (POC from Sessions 0015-0016, torn down)
- Deleted `agent/` package (Strands SDK stubs from Sessions 0001-0005)
- Deleted `oauth/routes.py` + `oauth/tests/test_callback.py` (replaced by api/onboarding.py)
- Deleted `api/auth.py`, `api/routes/calls.py`, `api/routes/practices.py` (unimplemented stubs)
- Removed `poc/` directory (git rm, was locally deleted but unstaged)
- Deleted `Documentation/` (13 files of copied AWS Connect Health public docs — we don't use that service)
- Deleted `docs/research/spike-fhir-result.json` (contained QA patient PII)
- Deleted `tools/lookup_patient/tool_schema.json` (orphaned AgentCore Gateway schema)
- Deleted `web/src/{api,components,pages}/README.md` (empty placeholder stubs)
- Deleted stale `forward-plan-revised.md` and `forward-plan-session-0014.md`
- Updated CI `run_synthetic_call.py` to be self-contained after agent/ removal
- Fixed pre-existing ruff lint errors across 5 packages (unused imports, unused variables)
- Staged session docs 0015 and 0016

### IaC cleanup
- Removed `AgentGatewayStack` from CDK code (dead infrastructure from Sessions 0007-0010)
- Destroyed orphaned `pf-voice-qa-agent-gateway` CloudFormation stack via `aws cloudformation delete-stack`
- Simplified dead ternary in audit-stack.ts (`? false : false` → `false`)
- Consolidated duplicate `oauthKmsKeyArn`/`oauthKmsKeyArnForGrant` props in lex-stack.ts
- Scoped `secretsmanager:GetSecretValue` from all secrets to `pf-voice-qa-*` pattern
- Scoped `connect:ClaimPhoneNumber` from `*` to specific Connect instance ARN
- Updated architecture.md to reflect direct tool bundling (no Gateway)

### PHI-safety timebomb fix
- `_load_system_prompt()` previously fell back to a hardcoded 4-line prompt with NO PHI safeguards if the prompt file was missing from the Lambda bundle
- Now raises RuntimeError — the Lambda fails loud at cold start rather than silently degrading
- Added test to verify RuntimeError is raised when no prompt file exists

### Bedrock IAM scoping incident
- Attempted to scope `bedrock:InvokeModel` from `*` to `arn:aws:bedrock:REGION::foundation-model/anthropic.*`
- **Broke live calls.** Cross-region inference profiles (`us.anthropic.claude-sonnet-4-6`) fan out to foundation-model ARNs in multiple regions (us-east-1, us-east-2, etc.) plus inference-profile ARNs with the account ID. The scoped policy missed these.
- First fix (adding inference-profile ARNs) still failed — a second call hit `us-east-2::foundation-model/anthropic.claude-sonnet-4-6`
- **Reverted `bedrock:InvokeModel` to `resource: *`** — cross-region inference requires it until AWS documents the full ARN set
- Lesson: the "verify before commitment" principle from CLAUDE.md applies to IAM scoping too. Scoping IAM on Bedrock cross-region inference requires primary-source documentation that doesn't exist yet.

### Repo hygiene
- Gitignored `test-results/` (Playwright artifact)
- Marked ADR-0012 (tools-as-MCP-via-Gateway) as superseded
- Updated glossary: removed Strands/AgentCore/KVS references, added Lex V2, code-hook Lambda, pf_org_uuid
- Added build/test/lint commands and package map to CLAUDE.md

### Deployment
- `cdk deploy --all -c env=qa` — all 8 stacks deployed successfully
- Critical catch: contact flow requires `escalationQueueArn` context parameter, otherwise the escalation branch (check-escalation → set-escalation-queue → transfer-to-escalation) is omitted and callers who need a human just get disconnected
- Escalation queue ARN: `arn:aws:connect:us-east-1:086514900943:instance/bc48ce14-1766-44c9-807b-4807e6010dd6/queue/56d2736b-5e63-454f-b01b-52591e650a55`

### Git remote
- Created private repo: https://github.com/durvester/Amazon-Connect-Health
- All commits pushed to remote

## Decisions made
- `practice_id` DDB column stays as-is (stores pf_org_uuid values, naming inconsistency deferred — rename requires table recreation)
- AgentGatewayStack removed from code AND AWS
- System prompt fallback removed in favor of hard error
- `bedrock:InvokeModel` stays at `resource: *` — cross-region inference profiles require it
- Secretsmanager and Connect IAM scoped to least-privilege (these worked correctly)

## Open questions
1. Should `escalationQueueArn` be hardcoded in `cdk.json` context defaults for QA, or stay as a CLI parameter?
2. When AWS documents cross-region inference profile ARN patterns, re-scope the Bedrock IAM policy
3. When to reconcile CLI-deployed resources as CDK IaC? (Session 0016 pickup note)

## Next session pickup

**The first thing the next session should do:**
1. Read this file
2. Read `docs/architecture.md` and `docs/context.md`
3. The repo is clean, deployed, and pushed. Production system on +16156250631 verified working.
4. **Deploy command (must include escalation queue):**
   ```bash
   cd infra && npx cdk deploy --all -c env=qa \
     -c escalationQueueArn="arn:aws:connect:us-east-1:086514900943:instance/bc48ce14-1766-44c9-807b-4807e6010dd6/queue/56d2736b-5e63-454f-b01b-52591e650a55"
   ```
5. **Forward plan priority order:**
   - Session 0018: Cognito user pool + auth middleware + dashboard skeleton (JTBD S1)
   - Session 0019: Dashboard onboarding wizard + call history page (JTBD S1, S3)
   - Session 0020: Number selection UI with area code picker (JTBD S2)
   - Session 0021: Business hours config + after-hours behavior (JTBD S4)
   - Session 0022: Number porting flow (JTBD S2)
   - Session 0023: Billing integration (monetization)
   - Session 0024: Bulk onboarding with SQS queue + DID pool (scale)

**Key context for next session:**
- PF auth already scales: each practice authorizes the Provider App, gets their own refresh token, stored KMS-encrypted in oauth-tokens table. No architectural changes needed.
- The onboarding flow (/oauth/start → /oauth/callback) already provisions end-to-end: tokens + DID + routing. Dashboard + Cognito are the missing pieces.
- `api/auth.py` and `api/routes/{calls,practices}.py` were deleted as stubs — re-implement when the dashboard is built.
- DID claiming is rate-limited by AWS at ~1-2 RPS. For 20K practices, use SQS queue or pre-reserve a DID pool.

## Files changed
- `tools/complete_verification/` (deleted)
- `tools/agent_action_group/` (deleted)
- `agent/` (deleted)
- `poc/` (deleted)
- `Documentation/` (deleted — copied AWS public docs)
- `oauth/src/oauth/routes.py` (deleted)
- `oauth/tests/test_callback.py` (deleted)
- `api/src/api/auth.py` (deleted)
- `api/src/api/routes/calls.py` (deleted)
- `api/src/api/routes/practices.py` (deleted)
- `docs/research/spike-fhir-result.json` (deleted — contained PII)
- `tools/lookup_patient/tool_schema.json` (deleted — orphaned Gateway schema)
- `web/src/{api,components,pages}/README.md` (deleted)
- `web/test-results/.last-run.json` (deleted + gitignored)
- `docs/sessions/forward-plan-revised.md` (deleted)
- `docs/sessions/forward-plan-session-0014.md` (deleted)
- `infra/lib/agent-gateway-stack.ts` (deleted)
- `infra/test/agent-gateway-stack.test.ts` (deleted)
- `tools/lex_code_hook/src/lex_code_hook/handler.py` (prompt timebomb fix + lint fixes)
- `tools/lex_code_hook/tests/test_handler.py` (new test + lint fixes)
- `infra/lib/lex-stack.ts` (IAM scoping attempted → reverted for Bedrock, kept for SecretsManager + prop consolidation)
- `infra/lib/api-stack.ts` (Connect IAM scoped to instance ARN)
- `infra/lib/audit-stack.ts` (dead ternary fix)
- `infra/bin/app.ts` (removed AgentGatewayStack + duplicate prop)
- `infra/test/lex-stack.test.ts` (removed duplicate prop)
- `Makefile` (removed dead packages from PYTHON_PKGS)
- `.gitignore` (added test-results/)
- `ci/src/ci/run_synthetic_call.py` (self-contained after agent/ removal)
- `ci/src/ci/mint_access_token.py` (dead import removal)
- `scripts/probe-fhir-resources.py` (parameterized hardcoded IDs)
- `docs/architecture.md` (removed Gateway references)
- `docs/decisions/0012-tools-as-mcp-via-gateway.md` (marked superseded)
- `docs/glossary.md` (updated for current architecture)
- `docs/roadmap.md` (added forward plan for Sessions 0018-0024)
- `CLAUDE.md` (added build/test/lint commands + package map)

## Notes for future Claude
- The `complete_verification` tool name still exists in lex_code_hook/handler.py as a tool_name string — it's the tool Claude calls, not an import. The logic is inline at handler.py:174-179.
- The `agent/` package was the Strands SDK stub. The actual agent logic is in `tools/lex_code_hook/` — the code-hook Lambda IS the agent brain.
- **DO NOT scope `bedrock:InvokeModel` IAM to specific ARN patterns.** Cross-region inference profiles (`us.anthropic.*`) fan out to foundation-model ARNs in unpredictable regions. This was tested and broke live calls twice. Keep `resource: *` until AWS documents the full ARN set.
- **Always pass `escalationQueueArn` when deploying.** Without it, the contact flow drops the escalation branch and callers who need a human just get disconnected. The ARN is `arn:aws:connect:us-east-1:086514900943:instance/bc48ce14-1766-44c9-807b-4807e6010dd6/queue/56d2736b-5e63-454f-b01b-52591e650a55`.
- `SearchAvailablePhoneNumbersV2` and `secretsmanager:GetSecretValue` IAM scoping DID work correctly — only Bedrock needed the revert.
- build/ directories exist on disk (setuptools artifacts) but are gitignored. They're harmless.
