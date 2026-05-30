// Per-environment configuration. ADR-0008 — the single source of truth
// for everything that differs across qa / staging / prod.
//
// Lambda code never imports this file. CDK reads it; CDK passes the
// resulting values to Lambdas via environment variables.

export type EnvName = "qa" | "staging" | "prod";

export interface EnvConfig {
  envName: EnvName;
  account: string;            // "TBD" until an account is provisioned
  region: string;
  logRetentionDays: number;
  removalPolicy: "DESTROY" | "RETAIN";
  ratelimitDefaultPerDay: number;
  resourcePrefix: string;     // used for table/bucket names + alias prefixes
}

export const envs: Record<EnvName, EnvConfig> = {
  qa: {
    envName: "qa",
    account: "000000000000",
    region: "us-east-1",
    logRetentionDays: 7,
    removalPolicy: "DESTROY",
    ratelimitDefaultPerDay: 100,
    resourcePrefix: "pf-voice-qa",
  },
  staging: {
    envName: "staging",
    account: "TBD",
    region: "us-east-1",
    logRetentionDays: 30,
    removalPolicy: "RETAIN",
    ratelimitDefaultPerDay: 100,
    resourcePrefix: "pf-voice-staging",
  },
  prod: {
    envName: "prod",
    account: "TBD",
    region: "us-east-1",
    logRetentionDays: 365,
    removalPolicy: "RETAIN",
    ratelimitDefaultPerDay: 1000,
    resourcePrefix: "pf-voice-prod",
  },
};

export function loadEnv(envName: string | undefined): EnvConfig {
  if (!envName || !(envName in envs)) {
    throw new Error(
      `--context env=<qa|staging|prod> required (got ${envName ?? "<unset>"})`,
    );
  }
  const cfg = envs[envName as EnvName];
  if (cfg.account === "TBD") {
    throw new Error(
      `env=${envName} has no account provisioned yet; update infra/config/envs.ts`,
    );
  }
  return cfg;
}
