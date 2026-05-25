# ADR-0017: Connect AI agent is provisioned via AwsCustomResource; PhysicalResourceId tracks prompt_version

**Status:** Superseded by [ADR-0018](0018-lex-orchestrates-nova-sonic-and-agentcore.md) (Session 0010 — `connect:CreateAIAgent` does not exist in the SDK and is not the actual API; AI agents in Connect refer to Amazon Q in Connect / Wisdom, which is not the voice surface).

**Date:** 2026-05-24 (Session 0009)

**Related:** ADR-0011 (Connect-native pivot), ADR-0013 (decision in
prompt), ADR-0012 (MCP via Gateway).

## Context

Session 0007 OQ #1 left open whether `AWS::Connect::AIAgent` would be
exposed in `aws-cdk-lib` by the time Session 0009 needed it. As of
2026-05-24, the L1 resource is not in `aws-cdk-lib` and the admin API
shapes (`CreateAIAgent`, `UpdateAIAgent`, `DeleteAIAgent`,
`DescribeAIAgent`) are reachable only through the Connect SDK.

The verification prompt (ADR-0013) lives in
`agent/src/agent/prompts/verification.md`. We want a deploy story
where editing the prompt in git + `cdk deploy` is the entire rollout
path — no console clicks, no separate prompt-management tool.

## Decision

ConnectStack provisions the AI agent via `AwsCustomResource` calling
`connect:CreateAIAgent` on stack create, with these specifics:

1. **Prompt text is read from disk at synth time** (`fs.readFileSync`)
   and embedded in the custom-resource parameters. A CDK diff before
   deploy shows the literal prompt change.

2. **PhysicalResourceId is `${aiAgentName}-${promptVersion}`** where
   `promptVersion` is parsed from the `<!-- prompt_version: ... -->`
   trailer in `verification.md`. Consequence: bumping the version
   string in the prompt file *replaces* the AI agent (CloudFormation
   sees a new physical id → delete old + create new). Leaving the
   version string alone but editing the prompt body **does not**
   reprovision — that's intentional: prompt edits within a version
   are dev-loop, version bumps are release events.

3. **`installLatestAwsSdk: true`** because `connect:CreateAIAgent` is
   a Nov-2025 admin API not yet baked into Lambda's built-in SDK.

4. **Tools are bound to the agent by Gateway ARN**, not by individual
   tool ARNs. AgentCore Gateway is the single MCP catalog (ADR-0012);
   the AI agent invokes any tool the Gateway exposes.

5. **The contact-flow stub is replaced** with an `InvokeAIAgent`
   action block referencing the agent id (resolved at deploy time
   from the custom-resource response field `AIAgentId`). Session
   attributes `practice_id`, `caller_phone`, `call_id` are passed so
   the agent populates `lookup_patient` inputs without extra prompts.

## Why PhysicalResourceId-per-version, not in-place update?

The naive design (stable `PhysicalResourceId`, onUpdate calls
`UpdateAIAgent`) needs the previous `AIAgentId` at synth time of the
update call. AwsCustomResource doesn't carry response fields across
invocations as input parameters; you'd need a Provider Framework
construct with cross-invocation state, or DescribeAIAgent indirection.

Tying the physical id to the version string keeps the implementation
small (≈40 lines, one AwsCustomResource) at the cost of one
delete+create cycle per version bump. The cycle is a handful of API
calls, not a service interruption — the contact flow refers to the
new id immediately after CFN updates.

Cost: one DeleteAIAgent + one CreateAIAgent per release. The CFN
update sequence is "create new → swap contact flow refs → delete
old," which has a brief window where two agents exist. Acceptable in
v1; if release frequency goes up, we move to the Provider Framework.

## Audit trail

Every deployed prompt maps 1:1 to a `prompt_version` string in git
history. The S3 audit bucket already records per-call agent
telemetry (ADR-0013 audit plan); the deployed version is captured in
the contact-flow log alongside.

## Kill criterion

If `AWS::Connect::AIAgent` lands in `aws-cdk-lib` before pilot, we
migrate to the L1 resource and supersede this ADR. The custom-resource
plumbing is contained to one block in `ConnectStack`.

## Files

- `infra/lib/connect-stack.ts` — `AwsCustomResource` + IAM grants +
  contact-flow `InvokeAIAgent` block.
- `agent/src/agent/prompts/verification.md` — canonical prompt text +
  trailing `<!-- prompt_version: ... -->` marker.
- `infra/test/connect-stack.test.ts` — assertions for the custom
  resource + Gateway-scoped role policy + flow handoff.
