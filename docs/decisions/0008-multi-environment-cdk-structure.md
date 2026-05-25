# ADR-0008: Multi-environment CDK structure (qa / staging / prod)

**Status:** Accepted

**Date:** 2026-05-23 (Session 0006)

## Context

Up to Session 0005 the CDK app (`infra/`) was empty scaffold — one
`app.synth()` call, no stacks, one passing jest "synthesizes without
errors" snapshot test. Session 0006 introduces the first two real
stacks (`audit`, `rate-limit`). Sessions 0007–0016 add Connect,
AgentCore, the OAuth API, the dashboard, the agent, and the per-tool
CDK. By the end of v1, the CDK app deploys ~10 stacks.

We are pre-production. The pilot practice will sit in PF QA. Eventually
we need staging and prod accounts. The decision to make now — before
any of the ten stacks exists — is **how environments are selected,
named, and configured**, so that:

1. The same CDK code synthesizes for any environment with no diffs.
2. Per-env values (account ID, region, log retention, removal policy,
   default rate-limit budgets) live in one place.
3. No Lambda code branches on `if env == "qa"`.
4. Stack names carry an environment suffix, so the same account could
   host two envs side by side if needed during cutover.
5. The QA-only sealed-box dev fixture (Session 0005) stays out of the
   *runtime* config path — even in QA, the deployed Lambdas read
   tokens from DDB (KMS-encrypted), not from a fixture.

This ADR locks the pattern in before the audit/rate-limit stacks land,
because retrofitting env-awareness onto already-deployed stacks
(re-naming, re-keying KMS aliases) is the kind of work that gets
deferred indefinitely.

## Decision

### Env selection — CDK context

`cdk synth`, `cdk deploy` etc. take `--context env=<name>`. The list
of legal env names is `qa`, `staging`, `prod`. `infra/bin/app.ts`
reads the context, falls back to `process.env.CDK_ENV`, fails fast if
neither is set or the value is not in the legal set.

```typescript
const envName = app.node.tryGetContext("env") ?? process.env.CDK_ENV;
if (!isValidEnv(envName)) {
  throw new Error(`--context env=<qa|staging|prod> required (got ${envName})`);
}
```

Rationale: CDK context is the documented "knob for synth-time choices"
in CDK itself. Env var is a fallback for CI ergonomics. No silent
default — the explicit choice is a feature, not friction.

### Per-env config — `infra/config/envs.ts`

```typescript
export type EnvName = "qa" | "staging" | "prod";

export interface EnvConfig {
  envName: EnvName;
  account: string;
  region: string;
  logRetentionDays: number;
  removalPolicy: "DESTROY" | "RETAIN";
  ratelimitDefaultPerDay: number;
  tablePrefix: string;
  bucketPrefix: string;
  kmsAliasPrefix: string;
}

export const envs: Record<EnvName, EnvConfig> = {
  qa:      { envName: "qa",      account: "086514900943", region: "us-east-1",
             logRetentionDays: 7,   removalPolicy: "DESTROY",
             ratelimitDefaultPerDay: 100,
             tablePrefix: "pf-voice-qa",   bucketPrefix: "pf-voice-qa",
             kmsAliasPrefix: "alias/pf-voice-qa" },
  staging: { envName: "staging", account: "TBD",          region: "us-east-1",
             logRetentionDays: 30,  removalPolicy: "RETAIN",
             ratelimitDefaultPerDay: 100,
             tablePrefix: "pf-voice-staging", bucketPrefix: "pf-voice-staging",
             kmsAliasPrefix: "alias/pf-voice-staging" },
  prod:    { envName: "prod",    account: "TBD",          region: "us-east-1",
             logRetentionDays: 365, removalPolicy: "RETAIN",
             ratelimitDefaultPerDay: 1000,
             tablePrefix: "pf-voice-prod", bucketPrefix: "pf-voice-prod",
             kmsAliasPrefix: "alias/pf-voice-prod" },
};
```

`account` is `"TBD"` for envs not yet provisioned. The CDK app errors
loudly if you try to synth a stack against an env whose account is
TBD (caught at `cdk.Environment` construction, not at deploy time).

### Stack names — env-suffixed

Every stack is `<purpose>-<env>`, e.g. `pf-voice-audit-qa`,
`pf-voice-rate-limit-qa`. Rationale: identical names across envs would
make CloudFormation drift impossible to read at a glance, and would
forbid co-hosting two envs in one account (which we may need during
prod cutover).

### Runtime config — env vars only

Lambda code **never** reads CDK context, never imports
`infra/config/envs.ts`, never branches on env name. CDK passes
everything in via Lambda environment variables:

```typescript
new lambda.Function(this, "LookupPatient", {
  environment: {
    AUDIT_TABLE_NAME: auditTable.tableName,
    AUDIT_BUCKET_NAME: auditBucket.bucketName,
    AUDIT_KMS_KEY_ARN: auditKey.keyArn,
    RATELIMIT_TABLE_NAME: rateLimitTable.tableName,
    PRACTICES_TABLE_NAME: practicesTable.tableName,
    TOKENS_TABLE_NAME: tokensTable.tableName,
    OAUTH_KMS_KEY_ARN: oauthKey.keyArn,
    // intentionally NO PF_FHIR_BASE_URL / PF_ACCESS_TOKEN here — those
    // are per-practice, read from DDB at runtime per ADR-0007.
  },
});
```

Tests of the Python code use `monkeypatch.setenv(...)` to inject the
same shape; `moto` provides the AWS services those names point at. No
test ever talks to CDK.

### Secrets — Secrets Manager + KMS per env

Each env has:
- One KMS CMK for OAuth credentials (`alias/<envprefix>-oauth-key`).
- One KMS CMK for audit/PHI data (`alias/<envprefix>-phi-key`).
- Per-practice client secrets in Secrets Manager under
  `<envprefix>/practice/<practice_id>/pf_client_secret`.

The sealed-box dev fixture (Session 0005) is **never** in the runtime
path. It exists only so the CI svc-integration layer can mint a PF QA
access token without a human OAuth flow. Even in QA, deployed
Lambdas read tokens from DDB (KMS-encrypted under
`alias/pf-voice-qa-oauth-key`).

## Consequences

### Good
- Same CDK code synthesizes for qa / staging / prod by toggling one
  context flag. Adding a new env (e.g., a per-customer prod tenant) is
  one config-object entry.
- No drift between envs at the code level. Differences are
  declarative, in `envs.ts`.
- Stack names self-document which env they belong to in the AWS
  console.
- Snapshot tests can synth each env and check the resulting template,
  catching env-specific regressions.
- Future "spin up a per-customer environment" is one config entry.

### Bad / accepted
- Two stacks differ only by `tablePrefix` — small amount of duplication
  vs. a more clever single-stack-with-resource-suffix design. Worth it:
  the obvious mental model wins over cleverness.
- `removalPolicy: DESTROY` in QA means `cdk destroy --context env=qa`
  will nuke the audit bucket and the DDB tables. Acceptable: QA is
  reproducible. Prod is `RETAIN`.

### Migration shape
- Session 0006 introduces `envs.ts`, the env-context reader in
  `bin/app.ts`, and the first two stacks following the pattern.
- Sessions 0007+ each add stacks that consume `envs.ts`. No session
  re-litigates the env model.
- When a new env is provisioned (e.g., staging account ID assigned),
  the only change is `envs.staging.account = "<new ID>"` in `envs.ts`.

## Alternatives considered

- **One stack per env, three copies of every stack file.** Rejected:
  drift is inevitable and untestable.
- **Resource-name-only env discrimination, no stack suffix.** Rejected:
  unreadable in the console; blocks co-hosting envs.
- **Lambda code reads env name from a runtime env var and branches.**
  Rejected: the *runtime* should not know about envs; only deployment
  should. If a Lambda needs different behavior in prod, that's a
  config table row, not a code branch.
- **AWS CDK Pipelines for env promotion.** Out of scope for v1.
  Adding when we have a staging account.

## Open questions

- Single deploy account vs. per-env accounts? Currently `qa` lives in
  `086514900943` (per CLAUDE.md). Staging and prod accounts TBD —
  decision lands when those accounts are requested. The structure
  here doesn't require any change either way.
- Region failover? v1 is single-region (`us-east-1`). When we add a
  second region, `EnvConfig` grows a `regions` array. Out of scope
  for v1.
