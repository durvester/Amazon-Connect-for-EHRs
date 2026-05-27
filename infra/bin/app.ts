#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";

import { loadEnv } from "../config/envs";
import { ApiStack } from "../lib/api-stack";
import { AuditStack } from "../lib/audit-stack";
import { CallsStack } from "../lib/calls-stack";
import { ConnectStack } from "../lib/connect-stack";
import { LexStack } from "../lib/lex-stack";
import { PhoneRoutingStack } from "../lib/phone-routing-stack";
import { PracticesStack } from "../lib/practices-stack";
import { RateLimitStack } from "../lib/rate-limit-stack";

const app = new cdk.App();

const envName = app.node.tryGetContext("env") ?? process.env.CDK_ENV;
const envConfig = loadEnv(envName);

const cdkEnv: cdk.Environment = {
  account: envConfig.account,
  region: envConfig.region,
};

// -- Foundational stores (Session 0006) --
const auditStack = new AuditStack(app, `${envConfig.resourcePrefix}-audit`, {
  env: cdkEnv,
  envConfig,
});

const rateLimitStack = new RateLimitStack(
  app,
  `${envConfig.resourcePrefix}-rate-limit`,
  { env: cdkEnv, envConfig },
);

// -- Multi-tenancy router (ADR-0014) --
const phoneRouting = new PhoneRoutingStack(
  app,
  `${envConfig.resourcePrefix}-phone-routing`,
  { env: cdkEnv, envConfig },
);

// -- Practice config + OAuth tokens (ADR-0020, Session 0012) --
const practicesStack = new PracticesStack(
  app,
  `${envConfig.resourcePrefix}-practices`,
  { env: cdkEnv, envConfig },
);

// -- Call metadata store (Session 0014) --
const callsStack = new CallsStack(
  app,
  `${envConfig.resourcePrefix}-calls`,
  { env: cdkEnv, envConfig },
);

// -- Lex bot with Nova Sonic (ADR-0018 + ADR-0019, Session 0012) --
const lexStack = new LexStack(app, `${envConfig.resourcePrefix}-lex`, {
  env: cdkEnv,
  envConfig,
  practicesTableName: practicesStack.practicesTable.tableName,
  tokensTableName: practicesStack.tokensTable.tableName,
  oauthKmsKeyArn: practicesStack.oauthKey.keyArn,
  auditBucketName: auditStack.bucket.bucketName,
  rateLimitTableName: rateLimitStack.table.tableName,
  practicesTableArn: practicesStack.practicesTable.tableArn,
  tokensTableArn: practicesStack.tokensTable.tableArn,
  auditBucketArn: auditStack.bucket.bucketArn,
  auditKmsKeyArn: auditStack.kmsKey.keyArn,
  rateLimitTableArn: rateLimitStack.table.tableArn,
  callsTableName: callsStack.table.tableName,
  callsTableArn: callsStack.table.tableArn,
});

// -- Voice surface: Connect instance + contact flow (ADR-0018) --
const escalationQueueArn =
  (app.node.tryGetContext("escalationQueueArn") as string | undefined) ??
  process.env.CDK_ESCALATION_QUEUE_ARN;

const connectStack = new ConnectStack(
  app,
  `${envConfig.resourcePrefix}-connect`,
  {
    env: cdkEnv,
    envConfig,
    phoneRoutingTable: phoneRouting.table,
    lexBotAliasArn: lexStack.botAliasArn,
    escalationQueueArn,
  },
);

// -- OAuth onboarding API (Session 0008) --
const pfClientSecretArn =
  (app.node.tryGetContext("pfClientSecretArn") as string | undefined) ??
  process.env.CDK_PF_CLIENT_SECRET_ARN ??
  `arn:aws:secretsmanager:${envConfig.region}:${envConfig.account}:secret:${envConfig.resourcePrefix}-pf-client-secret`;

const oauthRedirectUri =
  (app.node.tryGetContext("oauthRedirectUri") as string | undefined) ??
  process.env.CDK_OAUTH_REDIRECT_URI;

new ApiStack(app, `${envConfig.resourcePrefix}-api`, {
  env: cdkEnv,
  envConfig,
  phoneRoutingTable: phoneRouting.table,
  practicesTable: practicesStack.practicesTable,
  tokensTable: practicesStack.tokensTable,
  oauthKmsKey: practicesStack.oauthKey,
  connectInstanceId: connectStack.connectInstance.ref,
  connectInstanceArn: connectStack.connectInstance.attrArn,
  pfClientSecretArn,
  oauthRedirectUri,
});

app.synth();
