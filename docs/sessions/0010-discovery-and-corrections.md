# Session 0010 — Deploy discovery: ADR-0011 premise was wrong; pivot to Lex (ADR-0018)

**Date:** 2026-05-24
**Goal (originally):** First QA deploy of all six stacks; one full
onboarding round-trip; one smoke-test call against a claimed DID.
**Actual outcome:** Four of six stacks deployed successfully. The
attempt to deploy `pf-voice-qa-connect` surfaced three primary-source
contradictions with the Session 0007 architectural pivot, leading to
ADR-0018 (Lex-orchestrated voice with Nova Sonic on the bot locale,
AgentCore Gateway reached via a Lex code-hook Lambda).

## What was done

### Pre-deploy plumbing (kept, all green)

- **PF QA client_secret stashed in Secrets Manager:** new secret
  `pf-voice-qa-pf-client-secret` (real ARN
  `arn:aws:secretsmanager:us-east-1:086514900943:secret:pf-voice-qa-pf-client-secret-nCNxiK`).
  The CDK ApiStack picks this ARN up via the
  `pfClientSecretArn` context arg (already wired in Session 0008).
  Client_id, fhir_base_url, token_endpoint stay where they belong —
  in the per-practice `practices` DDB row written at onboarding time.
- **Lambda packaging fix (resolves Session 0008 OQ #1).** New helper
  `infra/lib/python-lambda-asset.ts` runs `pip install -t` inside
  `lambda.Runtime.PYTHON_3_12.bundlingImage` (Docker). Both Lambdas
  switched to `lambda.Architecture.ARM_64` so the bundled
  `aarch64-linux-gnu` compiled extensions (e.g. pydantic-core's
  mypyc) match the runtime.
- **`oauthRedirectUri` plumbed through CDK context.** ApiStack now
  accepts an optional prop wired from `--context oauthRedirectUri=...`
  via `bin/app.ts`. Resolves Session 0008 OQ #2 — the Function URL
  materializes at first-deploy; a second deploy passes the real URL.
- **AWS creds note.** CDK does not pick up SSO profile creds
  automatically. The deploy line is
  `eval "$(aws configure export-credentials --format env)" && npx cdk
  deploy ...`. The four-stack subset went green only after this.

### Deployed (four stacks, validated against CFN)

| Stack | Status | Notes |
|---|---|---|
| `pf-voice-qa-audit` | `CREATE_COMPLETE` | S3 Object Lock bucket live |
| `pf-voice-qa-rate-limit` | `CREATE_COMPLETE` | DDB per-(practice, ANI) table live |
| `pf-voice-qa-phone-routing` | `CREATE_COMPLETE` | DDB DID → practice_id router live |
| `pf-voice-qa-agent-gateway` | `CREATE_COMPLETE` | AgentCore Gateway + `lookup_patient` Lambda live |

Lambda packaging path is proven against real CFN — the bundled
`lookup_patient` asset weighs in around 35 MB (audit + oauth + boto3
+ fastapi etc.) and uploads cleanly.

### Not deployed (this session)

| Stack | Failure mode |
|---|---|
| `pf-voice-qa-connect` | Three sequential failures unmasked the architectural error (see below). Stack rolled back, deleted, code is in a placeholder state pending the Session-0011 rewrite. |
| `pf-voice-qa-api` | Never attempted — depends on a working connect stack output. |

### The three failures that surfaced the architecture problem

1. **IAM em-dash.** `ConnectAIAgentRole`'s description contained a
   U+2014 em-dash; IAM rejects descriptions outside ASCII +
   ¡-ÿ. Fixed by replacing with `-`. Real, narrow bug.
2. **`connect:CreateAIAgent` not in the AWS SDK.** The Session 0009
   `AwsCustomResource` block called `Connect.createAIAgent` with
   `installLatestAwsSdk: true` — the custom-resource Lambda returned
   *"Unable to find command named: CreateAIAgentCommand for action:
   CreateAIAgent in service package @aws-sdk/client-connect"*. This
   was the first signal that the Session-0009 ADR-0017 had the API
   wrong.
3. **Contact-flow JSON rejected (`InvalidContactFlowException`).** I
   had written an `InvokeAWSService` action calling DDB GetItem
   directly from the flow. No such action exists in Connect's flow
   language. The minimum-viable flow I tried after that was
   syntactically valid but never deployed — at this point I stopped
   guessing and went to the primary-source docs.

### Primary-source research findings (the actual reason for ADR-0018)

Verified against the official AWS docs as of 2026-05-24:

- **`connect:CreateAIAgent` does not exist.** The actual AI-agent
  admin API is `qconnect:CreateAIAgent` in
  `@aws-sdk/client-qconnect`. CFN resource is `AWS::Wisdom::AIAgent`.
- **Q in Connect AI agents are text-AI, not voice.** They drive
  Answer Recommendation, Self-Service text, Manual Search, Note
  Taking, Email Generative Answer. They are not what we'd want for
  voice verification.
- **Nova Sonic in Connect is configured on a Lex bot locale**, not
  as a standalone agent. Per `nova-sonic-speech-to-speech.html`:
  set the bot's speech model to "Speech-to-Speech: Amazon Nova
  Sonic" in the Conversational AI Bot admin UI. The contact flow
  still uses `GetCustomerInput` (Lex target) + a `Set voice` block.
- **No `InvokeAIAgent` contact-flow action exists.** The
  flow-language action list is
  `MessageParticipant`, `DisconnectParticipant`, `UpdateContactAttributes`,
  `InvokeLambdaFunction`, `InvokeFlowModule`, `TransferContactToQueue`,
  `GetCustomerInput`, the various `UpdateContact*` actions, etc.
- **No `InvokeAWSService` action either.** Calls to AWS APIs from a
  contact flow go through `InvokeLambdaFunction`.

These findings together force the conclusion that the Session-0007
pivot to "Connect native AI agent + AgentCore Gateway" was a misread
of November 2025 announcements. The correct architecture is in
ADR-0018.

## Decisions made

- **ADR-0018** (new, Session 0010): Lex bot orchestrates the call;
  Nova Sonic is the bot's speech model; AgentCore Gateway is reached
  via a Lex code-hook Lambda. Supersedes ADR-0001, ADR-0004,
  ADR-0010, ADR-0011, ADR-0017. **Path A (Lex)** chosen over Path B
  (KVS streaming) per user direction at session close.
- **Foundational stacks preserved.** audit, rate-limit, phone-routing,
  agent-gateway designs survive the architecture revision intact.
  The `lookup_patient` Lambda + `tool_schema.json` are unchanged.
- **`agent/src/agent/prompts/verification.md` preserved as-is.** The
  wording covers tool-call inputs/outputs, not the runtime carrying
  the prompt — it ports cleanly into a Lex code-hook Lambda.
- **`infra/lib/connect-stack.ts` is left in a non-deploying state**
  with a header comment pointing to ADR-0018 for the rewrite. Better
  than a half-rewrite that hides the broken assumption.
- **Two memories saved** in `~/.claude/.../memory/`:
  `feedback_research_before_commitment.md` (verify primary sources
  before ADR/CDK) and `feedback_jtbd_drives_architecture.md`
  (architecture must work back from quantifiable practice JTBDs).

## Open questions

1. **Lex CFN + Nova Sonic configuration.** `AWS::Lex::Bot` etc. are
   GA, but the locale-level Nova Sonic flag's CFN attribute path is
   not verified yet. Session 0011 first task is a primary-source
   pass before any CDK code lands. [[feedback_research_before_commitment]]
2. **Lex code-hook Lambda contract.** Confirm the dialog code-hook
   vs fulfilment code-hook input/output shapes. The verification
   prompt's decision policy currently assumes a single "ask
   question → call lookup_patient → reason over result → produce
   next utterance" loop; whether that maps to one intent or many
   needs validation against the docs.
3. **Multi-tenancy router in the flow.** `InvokeLambdaFunction` is
   the path. A new tiny Lambda `tools/router_lookup` reads
   `phone_routing` by `$.SystemEndpoint.Address` and returns
   `practice_id` as a Lex session attribute. ADR-0014's table
   schema is unaffected.
4. **What to do with the deployed `pf-voice-qa-agent-gateway`
   stack's `lookup_patient` Lambda env vars.** Currently empty
   strings (Session 0007 placeholder). Session 0011 wires the real
   DDB / KMS / S3 references when the Lex code-hook Lambda is
   designed — those need the same env to actually invoke the tool.

## Next session pickup

**The first thing Session 0011 should do — before any code:**

1. Read this file + ADR-0018 (the supersession chain matters).
2. Read `feedback_research_before_commitment.md` and
   `feedback_jtbd_drives_architecture.md` from memory.
3. **Do the JTBD-first architecture write-up.** User direction:
   work back from Jobs-To-Be-Done that the practice can quantify.
   - List the JTBDs for the v1 four use cases (patient verification
     + lab/imaging status + visit summary + document/referral
     status). For each: what the caller wants done, the practice's
     quantifiable success metric (staff-minutes saved per call,
     percent of calls fully handled, abandonment rate, etc.), and
     what minimum AI behaviour satisfies that.
   - Map each JTBD onto a tool surface (existing `lookup_patient`
     covers verification; the other three need new tool definitions).
   - Use that as the input to the Lex-bot intent design — intents
     map to JTBDs, not to AWS primitives.
4. **Then** start the primary-source research pass for Lex + Nova
   Sonic. Land it as a short doc (`docs/research/lex-nova-sonic-research.md`)
   with quotes + URLs from the official docs before any ADR/CDK.

**Only after (3) and (4):** start Session-0011 implementation. First
failing test for Session 0011 (provisional, depends on architecture
doc):
`infra/test/lex-stack.test.ts::bot_locale_uses_nova_sonic_speech_to_speech`.

**Exit criteria for Session 0011:**
- A reviewed JTBD architecture doc (`docs/architecture-jtbd.md` or
  similar) checked in.
- A primary-source-cited Lex + Nova Sonic research doc.
- A new `infra/lib/lex-stack.ts` and rewritten
  `infra/lib/connect-stack.ts` that synth clean.
- `make test-ci` green; cdk synth clean.
- Connect + Lex stacks deployed; one onboarding round-trip end-to-end.

**Prerequisite blocks before opening Session 0011:**

- User to confirm the JTBD candidates and their quantifiable metrics
  (Session-0011 work-back depends on them).
- Verify Connect flow language Lex-bot block (`GetCustomerInput`)
  parameters against the docs.
- Re-register the eventual production-domain redirect URI with
  Veradigm if/when the Function URL is replaced by a custom domain.

## Files changed

- `infra/lib/python-lambda-asset.ts` (new) — Docker-based bundling
  for Python Lambdas with local-package dependencies.
- `infra/lib/api-stack.ts` — bundling switched to
  `pythonLambdaCode([...])`; Lambda architecture set to ARM_64;
  `oauthRedirectUri` prop added.
- `infra/lib/agent-gateway-stack.ts` — same bundling +
  architecture change for `lookup_patient`.
- `infra/lib/connect-stack.ts` — em-dash IAM fix; AwsCustomResource
  AI-agent block disabled; contact-flow replaced with minimal
  placeholder; header comment pointing to ADR-0018 for the
  Session-0011 rewrite.
- `infra/bin/app.ts` — AgentGateway constructs before Connect;
  Gateway ARN piped to Connect props; `oauthRedirectUri` context
  arg wired.
- `infra/test/connect-stack.test.ts` — stub-arg update (AI-agent
  related assertions left in place; will be rewritten in
  Session 0011 when the new flow lands).
- `docs/decisions/0011-connect-native-ai-agent-pivot.md` — marked
  Superseded.
- `docs/decisions/0017-connect-ai-agent-via-custom-resource.md` —
  marked Superseded.
- `docs/decisions/0018-lex-orchestrates-nova-sonic-and-agentcore.md`
  (new).
- `docs/sessions/0010-discovery-and-corrections.md` (this file).
- AWS side-effects (out-of-band):
  - `pf-voice-qa-pf-client-secret` secret created in Secrets Manager
    with the value from `.env`.
  - 4 stacks live: audit, rate-limit, phone-routing, agent-gateway.
  - 2 stacks deleted clean: connect (3 attempts), api (never
    attempted).
  - The CDK bootstrap stack `CDKToolkit` was already present from a
    prior session.

## Notes for future Claude

- **`@aws-sdk/client-connect` does not have `CreateAIAgent`.** When
  the Session-0009 AwsCustomResource block tried it with
  `installLatestAwsSdk: true`, the bundled "latest" SDK still didn't
  have it because the API simply is not on the Connect service. The
  AI-agent admin API lives in **`@aws-sdk/client-qconnect`** as
  `CreateAIAgent`, and the CFN resource is **`AWS::Wisdom::AIAgent`**.
  This entire surface is text-AI for Amazon Q in Connect, not voice.
  See ADR-0018.
- **Connect contact flows have no `InvokeAWSService` action.** I
  spent a deploy cycle on this assumption. The flow-language action
  list is fixed; AWS-API calls from a flow go through
  `InvokeLambdaFunction` only. See the official
  [actions reference](https://docs.aws.amazon.com/connect/latest/APIReference/flow-language-actions.html).
- **Connect contact flows have no `InvokeAIAgent` action.** See
  above. Nova Sonic is invoked via the existing `GetCustomerInput`
  block targeting a Lex bot whose locale's speech model is set to
  "Speech-to-Speech: Amazon Nova Sonic." Per the
  [Nova Sonic admin guide](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html),
  this is configured in the Connect admin UI; whether it has a CFN
  surface is Session-0011 OQ #1.
- **IAM Role descriptions reject characters outside ASCII +
  ¡-ÿ.** Em-dashes and similar Unicode punctuation will
  blow up `iam:CreateRole`. ASCII hyphens only. Easy to grep before
  deploy: `grep -P '[\\x{2014}]' infra/lib/*.ts`.
- **Connect instance deletion is slow and orphans across CFN
  rollbacks.** When `pf-voice-qa-connect` failed mid-create on the
  first attempt, the Connect instance remained ACTIVE despite
  CloudFormation saying "Resource creation cancelled." I had to
  `aws connect delete-instance` manually before retrying, then
  `aws cloudformation delete-stack` to clear the ROLLBACK_COMPLETE
  state. Same trap will recur on any future failed connect-stack
  deploy.
- **CDK does not auto-pick-up SSO profile credentials.** The deploy
  command needs an explicit
  `eval "$(aws configure export-credentials --format env)"` in
  front. The Makefile should grow a `deploy-qa` target that does
  this automatically; tracked for Session 0011 or 0012.
- **`installLatestAwsSdk: true` is recommended for any
  AwsCustomResource that calls a recently-shipped API**, but it is
  not a guarantee — if the API isn't on the targeted service at
  all, no SDK version helps.
- **The harness drift this session exposed.** Three sessions
  compounded an architectural error because the cold-pickup ritual
  in `CLAUDE.md` does not require a primary-source verification
  pass at the top of any session that proposes a new AWS service
  surface. Saving as `feedback_research_before_commitment.md` —
  future sessions should treat that as binding.
