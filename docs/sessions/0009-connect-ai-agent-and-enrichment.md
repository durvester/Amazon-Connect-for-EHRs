# Session 0009 — Connect AI agent provisioning + Patient.read enrichment

**Date:** 2026-05-24
**Goal (one sentence):** Wire the Connect native AI agent end-to-end —
verification prompt authored to ADR-0013, AI agent provisioned via
`AwsCustomResource` against the Nov-2025 Connect admin API, the
contact-flow stub block replaced with a real `InvokeAIAgent` handoff —
and enrich `lookup_patient` candidates with a per-candidate
`Patient.read` fan-out so the agent has the disambiguation fields its
prompt depends on.

## What was done

Three pieces, TDD-first throughout:

1. **`lookup_patient` enrichment fan-out (Session 0007 OQ #3).**
   - New first failing test
     `tools/lookup_patient/tests/test_handler.py::test_candidates_carry_enrichment_fields`
     asserts every returned candidate carries `name_first`,
     `name_last`, `date_of_birth`, `phone_masked` sourced from a
     per-candidate Patient.read.
   - New `lookup_patient.fhir_client.read_patient` issues one
     `GET /Patient/{id}` per candidate with the same one-shot 401
     refresh-and-retry as `search_patient`; projects FHIR fields down
     to the four enrichment columns (`phone_masked` is last-four
     digits, never the full number — privacy invariant from the
     prompt).
   - Handler iterates candidates and merges enrichment into the
     output shape.
   - All `lookup_patient` unit tests updated to mock the new
     `Patient/{id}` GET; 3 new `read_patient` tests in
     `test_fhir_client.py`. 50 lookup_patient tests pass.

2. **Verification system prompt v1 (ADR-0013).**
   - `agent/src/agent/prompts/verification.md` rewritten from the
     0001 placeholder into a concrete prompt covering: information
     collection order, `lookup_patient` invocation contract, response
     interpretation (`candidates` / `rate_limited` /
     `credentials_expired` / `error`), candidate decision policy
     (zero / one / multiple), targeted disambiguation questions,
     escalation reasons, privacy invariants (never read names
     aloud before confirm, last-four phone only), out-of-scope topics.
   - Trailing `<!-- prompt_version: v1.0-2026-05-24 (Session 0009) -->`
     marker — the deploy mechanism keys off this string.

3. **Connect AI agent provisioning via `AwsCustomResource` (ADR-0017).**
   - ConnectStack reads the prompt file at synth time, parses the
     version marker, and creates a `Custom::ConnectAIAgent` whose
     `PhysicalResourceId` is `${aiAgentName}-${promptVersion}`. A
     prompt-version bump cycles the resource (CFN delete + create);
     prompt-body edits without a version bump don't reprovision
     (dev-loop iteration stays local until the user is ready to
     release).
   - `installLatestAwsSdk: true` — `connect:CreateAIAgent` is a
     Nov-2025 admin API not in Lambda's built-in SDK.
   - AI agent role's `bedrock-agentcore:InvokeAgentRuntime` grant is
     **scoped to the passed Gateway ARN** rather than `*` — a
     multi-tenancy hygiene win versus the Session 0007 placeholder.
   - Contact-flow stub `MessageParticipant` block replaced with an
     `InvokeAIAgent` action block. `SessionAttributes` carry
     `practice_id`, `call_id` (from `$.ContactId`), and
     `caller_phone` (from `$.SystemEndpoint.Address`) so the agent
     can populate `lookup_patient` inputs without extra prompts.
   - `app.ts` reordered: AgentGatewayStack now constructs before
     ConnectStack so the Gateway ARN can be passed to ConnectStack
     props.
   - 3 new jest assertions in `infra/test/connect-stack.test.ts`:
     handoff is `InvokeAIAgent` (no stub copy left), custom resource
     exists with the right IAM, Gateway ARN is the only Gateway the
     role can invoke. Total infra jest is now 34 (was 31).

### Result

- `make test-ci` green across all four layers.
- Python: 141 tests (was 138; +3 from `read_patient` in
  `test_fhir_client.py`; +1 from the new enrichment test in
  `test_handler.py` — net is +4 minus 0 deletions and one rename of
  the bundle id constant; numbers per `make test-ci-unit` output).
- Jest: 34 tests (was 31; +3 in `connect-stack.test.ts`).
- `cdk synth --context env=qa` clean; all 6 stacks present.

## Decisions made

- **ADR-0017** — AI agent provisioned via `AwsCustomResource` with
  `PhysicalResourceId` keyed on the prompt version string. Rationale:
  CFN coverage for `AWS::Connect::AIAgent` still missing as of
  2026-05-24; the version-keyed physical id keeps a 1:1 mapping
  between deployed agents and git-versioned prompts at the cost of a
  delete+create per release.
- **Patient.read fan-out, not search-bundle projection** (no ADR —
  follows Session 0007 OQ #3's directive). The Lambda treats search
  as id-discovery and `Patient.read` as the canonical fetch. If PF
  ever trims search-bundle Patient resources, we don't notice.
- **`phone_masked` is last-four digits only** (no ADR — follows the
  prompt's privacy invariant). Implemented in
  `_project_enrichment` in `fhir_client.py`.
- **Prompt-version bump = release event; body edit = dev-loop**
  (captured in ADR-0017's PhysicalResourceId reasoning). The trailer
  comment is the contract.

## Open questions

1. **Exact `InvokeAIAgent` block JSON shape.** The contact-flow
   action `Type: "InvokeAIAgent"` is what Connect's contact-flow
   schema appears to use, but I have not deployed yet to confirm —
   the unit tests only assert string presence in the rendered flow
   content. First QA deploy will either accept the block or come
   back with a schema error; if the latter, the block name is the
   only thing that changes.
2. **Exact `Connect.createAIAgent` request shape.** Same caveat:
   `Name`, `Type: "MANUAL"`, `Configuration.ManualConfiguration.{PromptOverride,Tools,ModelId,ModelConfiguration}`,
   `AssociationConfiguration.InstanceId` is the best-effort shape
   read from the API reference. First deploy will validate.
3. **AgentCore Gateway 30s tool-invocation timeout** still
   unmeasured under real-traffic — carried forward from Session 0007.
   Session 0009 didn't add real-traffic load.
4. **`agent/src/agent/agent.py` + `agent.config` are pre-pivot
   stubs.** Session 0007's pivot moved the agent loop out of our
   process (it's now inside Connect). The `pf-voice-agent` Python
   package still exists for the prompt file + any future eval
   harness. Auto-mode left the stubs untouched.

## Next session pickup

**The first thing the next session should do:**

1. Read this file + ADR-0017.
2. Run baseline:
   ```sh
   make test-ci      # 141 python + 34 jest + ui-e2e + agent-e2e
   cd infra && npx cdk synth --context env=qa   # all 6 stacks clean
   ```
3. Decide: deploy QA now (Session 0010 = "first real deploy") or
   keep iterating on prompt/tool surface first (Session 0010 =
   "eval harness for the prompt").

**Goal for Session 0010 (recommended, pending user direction):**
First QA deploy of the 6-stack set — `pf-voice-qa-{audit, rate-limit,
phone-routing, agent-gateway, connect, api}` — plus the deferred
Session 0008 OQ #1 work (real `pip install -t build/` Lambda
packaging for the api stack), and resolve the OQs above by
observing real CFN responses to the `InvokeAIAgent` action and the
`createAIAgent` admin call. A deploy is also the cleanest way to
discover the Gateway tool-invocation p99 against PF QA.

**First failing test for Session 0010 (suggested):**
`infra/test/deploy-smoke.test.ts::stack_outputs_present_after_deploy`
— or equivalent — depending on the eval-harness vs deploy choice.

**Exit criteria for Session 0010 (deploy-track):**
- `cdk deploy --all` succeeds against the QA account.
- A test call to the QA-claimed DID reaches the contact flow,
  resolves a known `practice_id` from `phone-routing`, hands off to
  the AI agent, which calls `lookup_patient` against PF QA and
  returns enriched candidates.
- Audit bucket has the expected per-probe records.

## Files changed

- `tools/lookup_patient/src/lookup_patient/fhir_client.py` —
  `read_patient` + `_project_enrichment` + `_PHONE_DIGITS_RE`.
- `tools/lookup_patient/src/lookup_patient/handler.py` — fan-out
  loop replaces the prior single-shape conversion.
- `tools/lookup_patient/tests/test_handler.py` — new
  `test_candidates_carry_enrichment_fields`; existing
  single-candidate tests gained `_mock_single_patient_read()` calls.
- `tools/lookup_patient/tests/test_fhir_client.py` — 3 new
  `read_patient` tests (enrichment projection, 401 refresh, missing
  fields).
- `agent/src/agent/prompts/verification.md` — full rewrite (v1.0).
- `infra/lib/connect-stack.ts` — `AwsCustomResource` for the AI
  agent; `aiAgentRole` moved before the agent so the resource can
  pass the role; Gateway-ARN-scoped IAM; contact-flow handoff block
  is now `InvokeAIAgent`; the verification flow depends on the AI
  agent.
- `infra/lib/connect-stack` props — `agentCoreGatewayArn: string`
  added.
- `infra/bin/app.ts` — AgentGatewayStack now constructs before
  ConnectStack; Gateway ARN piped through.
- `infra/test/connect-stack.test.ts` — 3 new assertions; build
  helper passes a stub Gateway ARN.
- `docs/decisions/0017-connect-ai-agent-via-custom-resource.md` (new).
- `docs/sessions/0009-connect-ai-agent-and-enrichment.md` (this file).

## Notes for future Claude

- **`PhysicalResourceId.of(\`${aiAgentName}-${promptVersion}\`)` is
  the rollout mechanism.** If you edit the prompt and `cdk deploy`
  doesn't seem to do anything, you forgot to bump the
  `<!-- prompt_version: ... -->` trailer. That's not a bug — it's
  the intended dev-loop vs release-event split (ADR-0017).
- **`installLatestAwsSdk: true` is non-optional** for the AI-agent
  custom resource. Don't switch it off in a future "tidy-up." The
  Connect admin APIs are too new for Lambda's bundled SDK and the
  resource will throw an unhelpful "service has no operation
  named CreateAIAgent" error if you do.
- **The AI agent role's Gateway grant is ARN-scoped.** If you ever
  add a second Gateway, pass *both* ARNs into ConnectStack props
  rather than widening to `*`. Multi-tenancy hygiene
  ([[feedback_multitenancy_first]]).
- **`Patient.read` enrichment is one HTTP call per candidate.** With
  the current 6-format phone probe (ADR-0006) finding 1 candidate
  most of the time, this is +1 RTT per call — not material. If
  ambiguous bundles grow large in production, consider parallel
  `Patient.read` via `concurrent.futures.ThreadPoolExecutor`. Not
  needed in v1.
- **`phone_masked` is *only* last four digits.** Never project the
  full E.164. The prompt also says "never read full phone aloud" —
  the field shape enforces that even if the prompt ever drifts.
- **The verification flow has `addDependency(aiAgent)`.** This is
  load-bearing — without it, CFN may try to create the contact flow
  before the AI agent exists, and `getResponseField("AIAgentId")`
  resolves to a dangling token.
- **The agent loop in `agent/src/agent/agent.py` is dead code post-
  pivot** (Session 0007). It's left for the eventual eval harness
  (Session 0013), not as a runtime dependency. Don't try to fix
  imports there; just delete it when the eval harness needs a clean
  slate.
