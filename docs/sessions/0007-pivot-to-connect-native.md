# Session 0007 — Pivot to Connect-native AI agent + AgentCore Gateway

**Date:** 2026-05-23
**Goal (one sentence):** Pivot the voice stack from KVS + container-hosted
AgentCore Runtime + Strands to Connect's Nov-2025 native AI agent +
AgentCore Gateway + MCP tools, land the IaC + multi-tenancy router,
slim `lookup_patient` to candidates-only return, and document the
decisions across four new ADRs — all with `make test-ci` green.

## What was done

The session began with the original goal (Connect + KVS + AgentCore
Runtime plumbing spike) and produced a working stack + 7 jest tests +
ADR-0010. Mid-session, conversation with the user surfaced two
realizations that forced a complete rewrite:

1. AWS launched **Connect-native AI agents** at re:Invent November 2025,
   powered by Nova Sonic, consuming tools via MCP through
   **AgentCore Gateway**. This collapses every layer between Connect and
   the tools — no KVS, no custom AgentCore Runtime, no Strands.
2. Amazon Connect *Health* (March 2026 launch) ships a GA Patient
   Verification agent, but Practice Fusion is not on the named EHR
   partner list (Veradigm, Greenway, Netsmart, Redox, HealthLake). We
   ride the same Connect-native plumbing with our own tools rather
   than consuming the prebuilt agent.

The user approved a pivot plan. The KVS work was reverted before any
deploy. The rest of the session implemented the new architecture
test-first, with ADR-driven discipline.

### GA / HIPAA gate (verified before any new CDK landed)

| Service | GA | HIPAA | us-east-1 |
|---|---|---|---|
| Amazon Connect | Yes (long-standing) | Listed directly | ✓ |
| Connect AI agents (Nov 2025) | Yes | Inherited via Connect | ✓ |
| Bedrock AgentCore | Yes | Listed directly | ✓ |
| AgentCore Gateway | Yes | Inherited via AgentCore | ✓ |
| Nova 2 Sonic (Dec 2025) | Yes | Bedrock HIPAA umbrella | ✓ |

AWS HIPAA-eligible-services page note covers inherited eligibility:
*"generally available features of each of the HIPAA eligible services
listed are also considered HIPAA eligible."* BAA confirmed in force for
account `086514900943` by the user.

### Reverted (pre-pivot, never deployed)

- `infra/lib/connect-agentcore-stack.ts` and its 7-test jest file
- `agent/src/agent/hello_world_handler.py`
- `docs/runbooks/connect-bootstrap.md`
- `docs/decisions/0010-connect-agentcore-wiring.md`
- ConnectAgentCoreStack wiring in `infra/bin/app.ts`

After revert, `make test-ci` re-verified green at the Session-0006
baseline before any new code landed.

### ADRs landed

- **ADR-0011** — Pivot to Connect native AI agent + AgentCore Gateway
  + MCP tools. Supersedes ADR-0001 (BedrockAgentCore-over-Lex framing
  irrelevant when Connect owns the runtime), ADR-0004 (no custom
  Strands loop), ADR-0010 (wrong wire). Retains ADR-0002 (Nova Sonic).
- **ADR-0012** — Tools-as-MCP-via-Gateway as the canonical
  extensibility surface. Lambda + `tool_schema.json` + Gateway Target
  as the three artifacts every tool ships with. 30 s timeout
  documented; OpenAPI-/ToolSchema-as-contract principle codified.
- **ADR-0013** — Verification decision logic in the agent prompt;
  Lambdas are thin FHIR adapters. Audit defensibility plan covering
  transcript + tool-call log + agent decision capture into the
  existing S3 Object Lock audit bucket. Kill criterion: <99% verdict
  stability on the Session-0013 eval corpus reverts the decision back
  to code (ADR-0017 if/when that fires).
- **ADR-0014** — Per-practice dedicated DID + `phone_routing` table
  (DID → practice_id) as the canonical multi-tenancy router. Explicit
  multi-tenancy chain end-to-end (DID → practice_id → fhir_base_url +
  tokens + audit context). Cost note: ~$1/DID/month × 20K practices =
  ~$240K/year — flagged but accepted for v1.

### New `routing/` Python package

- `routing/pyproject.toml`, `routing/src/routing/__init__.py`,
  `routing/src/routing/phone_routing_store.py`
- `PhoneRoutingStore` with three operations: `claim(phone_number,
  practice_id, connect_instance_id)`, `resolve(phone_number) ->
  practice_id | None`, `release(phone_number)`.
- Exceptions: `PhoneRoutingStoreError`, `PhoneNumberAlreadyClaimed`
  (different-practice double-claim rejected), `PhoneNumberNotFound`
  (release of unknown DID raises; reads return None).
- Idempotency: same-practice re-claim is silently OK; conditional
  DDB write makes the check + put atomic.
- `routing/tests/test_phone_routing_store.py` — 9 moto-mocked unit
  tests covering claim, resolve (active + released + missing),
  release (happy + missing), idempotent re-claim, double-claim
  rejection, full-record audit-friendly read.
- `Makefile` — `routing` added to `PYTHON_PKGS`.

### New CDK stacks (ADR-0008 env-context pattern preserved)

- `infra/lib/phone-routing-stack.ts` — PAY_PER_REQUEST DDB table
  partitioned by `phone_number`. PITR enabled in prod only. Mirrors
  `rate-limit-stack.ts` shape.
- `infra/lib/connect-stack.ts` — Connect instance + contact flow
  that uses `InvokeAWSService` against the `phone_routing` table
  (native DDB integration, no glue Lambda) to resolve `practice_id`,
  sets it as a contact attribute, then hands off to the AI agent
  (Session 0009 swaps the stub for the real AI-agent block). Includes
  a dedicated contact-flow service role (grants only `GetItem` on the
  routing table) and the AI-agent execution role (Nova Sonic invoke +
  AgentCore Gateway invoke).
- `infra/lib/agent-gateway-stack.ts` — AgentCore Gateway + one Lambda
  Target for `lookup_patient`. Gateway naming uses the hyphenated
  resourcePrefix (`pf-voice-qa-gw`) — runtime validator rejects
  underscores despite the looser type declaration. Lambda timeout is
  25 s, 5 s under the Gateway's 30 s tool-invocation cap (ADR-0012).
- `infra/bin/app.ts` — wires all five stacks (audit, rate-limit,
  phone-routing, connect, agent-gateway) under
  `${envConfig.resourcePrefix}-<purpose>` names.

### `lookup_patient` slim refactor (ADR-0013)

- Event fields renamed: `phone` → `caller_phone`, `dob` →
  `date_of_birth`. Added optional `name_first`, `name_last` (unused
  by the FHIR client today; reserved for the agent's prompt).
- Return shape changed: dropped `match: single|multiple|none` and
  `patient_id` and `winning_format`. New shape:
  `{status: "candidates"|"rate_limited"|"credentials_expired"|"error", candidates: [{patient_id, probe_origin}], probes_tried}`.
- `fhir_client.search_patient` is unchanged. The handler translates
  the old verdict shape into the new candidates shape — keeps the
  refactor contained to one file.
- Per-candidate enrichment (name, dob, phone_masked) is deferred to
  Session 0009 (a Patient.read per candidate). For Session 0007's
  test surface, candidates carry only `patient_id` + `probe_origin`.
- `tools/lookup_patient/tool_schema.json` (new) — AgentCore
  ToolSchema format (not OpenAPI 3.0 — Gateway's Lambda targets use
  this proprietary format). Documents inputs (practice_id, call_id,
  caller_phone required; name + dob optional) and outputs (status +
  candidates + probes_tried). One source of truth for the Lambda +
  Gateway contract.
- All 10 unit tests in `tools/lookup_patient/tests/test_handler.py`
  rewritten to assert the new shape. Audit-per-probe assertion
  preserved verbatim.
- `tools/lookup_patient/tests/test_integration_handler.py` updated
  for the new event field names + return shape; remains gated by
  PF_* env vars (skipped in CI).

### Documentation

- `CLAUDE.md` — "Not Amazon Connect Health (Epic-only)" line removed
  (stale as of March 2026 Connect Health launch). Replaced with
  "Not Amazon Connect Health prebuilt agents (PF not a named EHR
  partner)." Added a section explaining the post-pivot architecture
  at a glance.
- `docs/architecture.md` — call-flow diagram + component map rewritten
  for the post-pivot wire. KVS, Strands, AgentCore Runtime removed
  from the component map. AgentCore Gateway, Nova 2 Sonic, native AI
  agent, phone_routing added.
- `docs/roadmap.md` — top-of-file pivot notice points readers at
  ADR-0011 + the plan file. Session 0007 entry rewritten with the new
  goal, exit criteria, and files-changed list. Sessions 0008–0015
  left as pre-pivot text with a header note explaining what's stale;
  full rewrite deferred to avoid blowing session scope (next session
  picks up the OAuth onboarding API, which the pre-pivot text
  describes correctly in direction if not detail).
- `docs/decisions/0001-bedrock-agentcore-over-lex.md` and
  `docs/decisions/0004-python-strands-sdk.md` — both marked
  **Superseded by ADR-0011** with a "Do not implement against this
  ADR" note.

### Result

- **`make test-ci` green across all four layers** (Principle #2,
  binding from Session 0006 forward).
- Python: 117 tests (was 109, +8 net — +9 routing, –1 lookup_patient
  `missing_dob` test dropped since `date_of_birth` is no longer
  required by the slim handler).
- Jest: 25 tests (was 9 — the Session-0006 audit + rate-limit stack
  tests; +16: 6 phone-routing, 5 connect, 5 agent-gateway). The 7
  jest tests from the reverted ConnectAgentCoreStack were removed.
- `cdk synth --context env=qa` clean for all five stacks:
  `pf-voice-qa-audit`, `pf-voice-qa-rate-limit`,
  `pf-voice-qa-phone-routing`, `pf-voice-qa-connect`,
  `pf-voice-qa-agent-gateway`.

## Decisions made

- **ADR-0011** — pivot. Captured the full rationale and the kill
  criterion (revert to Pipecat-on-AgentCore-Runtime if Session 0009
  cannot demonstrate ADR-0006 compliance in a real call).
- **ADR-0012** — MCP-via-Gateway. Locked the tool-shipping pattern
  (Lambda + tool_schema.json + Gateway Target) before any new tool
  lands; Sessions 0010–0012 will follow it verbatim.
- **ADR-0013** — decision logic in prompt. User-chosen against the
  Plan-agent's safer recommendation; risks accepted and audit plan
  documented, with kill criterion at Session 0013's eval.
- **ADR-0014** — per-practice DID + `phone_routing`. User caught the
  multi-tenancy gap during plan review; turned into a clean
  data-driven router with a new package + new CDK stack.
- **GA/HIPAA gate is a hard gate** (no ADR — operational rule).
  Verified before any new CDK landed; captured in ADR-0011's gate
  table. Re-run before pilot (Session 0014) for confirmation.
- **Don't roll our own MCP server** (covered by ADR-0012). Gateway
  converts OpenAPI/ToolSchema/Lambda → MCP for us; if we ever need
  something Gateway can't express, we re-shape the tool first.
- **Roadmap full-rewrite deferred** (no ADR — judgment call). Sessions
  0008–0015 in `docs/roadmap.md` retain pre-pivot framing with a
  header note; a clean rewrite is a session unto itself and didn't
  fit Session 0007's exit criteria.
- **OpenAPI 3.0 was the *wrong* contract format for Lambda targets**
  (no ADR — empirical correction). The CDK ToolSchema construct for
  Lambda Gateway targets uses AgentCore's proprietary ToolDefinition
  JSON, not OpenAPI 3.0. ADR-0012's prose was tightened to say
  "ToolSchema" (or "OpenAPI when target is an HTTPS endpoint, not a
  Lambda"). File extension is `.json`.

## Open questions

1. **Connect AI agent CFN coverage.** As of GA, the AI-agent
   configuration (prompt text, tool bindings, model selection) is
   reachable via the Connect AI-agent admin API but may or may not
   be exposed by `AWS::Connect::AIAgent` in current `aws-cdk-lib`.
   Session 0009 confirms; if absent, we wire via `AwsCustomResource`
   per ADR-0011 OQ.
2. **AgentCore Gateway HIPAA inheritance** — eligibility holds via the
   page note, but worth re-confirming with the AWS account team before
   pilot. Session 0014 captures the answer.
3. **Per-candidate Patient.read enrichment.** Session 0007 returns
   `{patient_id, probe_origin}` per candidate. Session 0009 adds the
   Patient.read fan-out for `{name_first, name_last, date_of_birth,
   phone_masked}` so the agent can disambiguate without exposing PHI
   prematurely.
4. **DID claim rate at scale.** AWS Connect rate-limits
   `claim_phone_number`. Session 0008's onboarding API discovers the
   actual limit; bulk onboarding may need chunking.

## Next session pickup

**The first thing the next session should do:**

1. Read this file (especially Decisions made — ADR-0011's pivot is
   binding, ADR-0014's `phone_routing` table is the multi-tenancy
   router every new code path must respect).
2. Read ADR-0011, 0012, 0013, 0014 in `docs/decisions/`.
3. Read `docs/roadmap.md` Session 0008 entry — note the top-of-file
   pivot notice: the Strands/AgentCore-Runtime framing is stale, but
   the OAuth-onboarding-API direction is correct.
4. Run baseline:
   ```sh
   make test-ci      # 117 Python + 25 jest + ui-e2e + agent-e2e
   cd infra && npx cdk synth --context env=qa   # all 5 stacks clean
   ```
5. Skim the plan file at
   `/Users/m858450/.claude/plans/i-spoke-to-somone-expressive-cake.md`
   — the session 0007–0015 plan table is the canonical short-form
   successor map.

**Goal for Session 0008 (per pivoted plan):** OAuth onboarding API +
DID claim. FastAPI on Lambda exposing `/oauth/start` and
`/oauth/callback`. On callback success, write `practices_store` row,
write `token_store` row, call `connect.claim_phone_number` for a US
DID against the Connect instance from Session 0007, write the
`phone_routing` row, return the DID to the caller for them to publish.

**First failing test for Session 0008:**
`api/tests/test_oauth_callback.py::callback_claims_did_and_writes_phone_routing`

**Exit criteria for Session 0008:**
- New FastAPI routes deployed via a new `infra/lib/api-stack.ts` that
  follows ADR-0008.
- Real PF QA integration test exercises the full onboarding round-
  trip (OAuth grant → DID claim → all four DDB writes happen
  atomically).
- `make test-ci` green.

**Prerequisite blocks before opening 0008:**
- A PF Provider App registration with a redirect URL pointing at the
  QA API Gateway domain (or a placeholder that Session 0008 swaps in
  once deployed).
- Confirm AWS Connect rate-limits for `claim_phone_number` —
  search-available-phone-numbers + claim is documented at ~1-2/s; if
  bulk onboarding is in scope, throttle accordingly.

## Files changed

- `infra/lib/{phone-routing-stack,connect-stack,agent-gateway-stack}.ts` (new)
- `infra/test/{phone-routing-stack,connect-stack,agent-gateway-stack}.test.ts` (new, 16 tests)
- `infra/bin/app.ts` — wires the three new stacks
- `routing/pyproject.toml`, `routing/src/routing/__init__.py`,
  `routing/src/routing/phone_routing_store.py`,
  `routing/tests/{__init__.py,test_phone_routing_store.py}` (new
  package, 9 tests)
- `Makefile` — `routing` added to `PYTHON_PKGS`
- `tools/lookup_patient/src/lookup_patient/handler.py` — ADR-0013
  slim refactor
- `tools/lookup_patient/tests/test_handler.py` — assertions updated
- `tools/lookup_patient/tests/test_integration_handler.py` — event
  field names + return shape updated
- `tools/lookup_patient/tool_schema.json` (new)
- `docs/decisions/0011-connect-native-ai-agent-pivot.md` (new)
- `docs/decisions/0012-tools-as-mcp-via-gateway.md` (new)
- `docs/decisions/0013-decision-logic-in-prompt.md` (new)
- `docs/decisions/0014-per-practice-did-phone-routing.md` (new)
- `docs/decisions/0001-bedrock-agentcore-over-lex.md` — Superseded
- `docs/decisions/0004-python-strands-sdk.md` — Superseded
- `CLAUDE.md` — Connect Health line revised; post-pivot architecture
  blurb added
- `docs/architecture.md` — diagram + component map rewritten
- `docs/roadmap.md` — top-of-file pivot notice; Session 0007 entry
  rewritten
- *Deleted* (never deployed):
  `infra/lib/connect-agentcore-stack.ts`, its test,
  `agent/src/agent/hello_world_handler.py`,
  `docs/runbooks/connect-bootstrap.md`,
  `docs/decisions/0010-connect-agentcore-wiring.md`

## Notes for future Claude

- **The Connect-native AI agent is the new runtime.** It owns audio,
  ASR, TTS, and the agent loop. We own only the system prompt (in the
  repo, deployed via CDK in Session 0009) and the tools (Lambdas
  exposed via Gateway). If a future session is tempted to add a
  Strands agent loop, a container image, or a KVS stream — point them
  at ADR-0011 first.
- **AgentCore Gateway naming.** Runtime validator rejects underscores
  despite the type-declaration hint allowing them. Use the hyphenated
  `resourcePrefix` directly. The early Session 0007 mistake here cost
  one test re-run.
- **Tool schema format gotcha.** Lambda Gateway targets use
  AgentCore's proprietary ToolSchema JSON (a list of
  `{name, description, inputSchema, outputSchema}`), NOT OpenAPI 3.0.
  ADR-0012 reads "OpenAPI as contract" — that's accurate for
  *HTTPS-endpoint* targets, but Lambda targets are ToolSchema. The
  shape is morally equivalent (JSON Schema for inputs/outputs); just
  use the right file format per target type.
- **Multi-tenancy chain is data-driven end to end.** DID resolves to
  `practice_id` at call start (`phone_routing`), which keys every
  downstream store. Never hardcode a practice; never assume single-
  tenant. The user reviews proposed designs for multi-tenancy gaps
  ([[multitenancy-first]] memory) — pre-empt by tracing the chain
  in every new piece of plumbing.
- **fhir_client is unchanged this session.** The slim refactor was
  done entirely in `handler.py` (verdict → candidates translation).
  Don't go searching for a refactor in `fhir_client.py` — there
  isn't one. The literal-telecom-search rule (ADR-0006) stays in
  the FHIR client where it belongs.
- **The session-0007 plan file**
  (`/Users/m858450/.claude/plans/i-spoke-to-somone-expressive-cake.md`)
  is the canonical short-form pivot map. Useful when reconciling
  the still-pre-pivot prose in `docs/roadmap.md` sessions 0008–0015.
- **Audit eval comes in Session 0013.** ADR-0013 puts verification
  reasoning in the prompt. Until the eval suite runs and ≥99%
  verdict stability is demonstrated, treat the verification gate as
  *probationary* — the kill criterion is real, not aspirational.
