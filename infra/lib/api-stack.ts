import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";
import { pythonLambdaCode } from "./python-lambda-asset";

export interface ApiStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
  readonly phoneRoutingTable: dynamodb.ITable;
  readonly practicesTable: dynamodb.ITable;
  readonly tokensTable: dynamodb.ITable;
  readonly oauthKmsKey: kms.IKey;
  readonly connectInstanceId: string;
  readonly connectInstanceArn: string;
  readonly pfClientSecretArn: string;
  readonly oauthRedirectUri?: string;
}

/**
 * OAuth onboarding API (Session 0008).
 *
 * A FastAPI app (api package, Mangum adapter) on a Python Lambda,
 * fronted by a Lambda Function URL. Practices hit /oauth/start, get
 * 302'd to PF's SMART authorization endpoint, then return through
 * /oauth/callback — where we exchange the code, persist the practice's
 * OAuth-adjacent config + KMS-encrypted tokens, claim a Connect DID,
 * and write the multi-tenancy router row that ties the DID to the
 * practice (ADR-0014).
 *
 * Resources created here:
 *
 *   - oauth-state DDB table        (state ↔ PKCE pair, single-use, TTL'd)
 *   - oauth-tokens DDB table       (KMS-encrypted access + refresh per practice)
 *   - oauth-tokens KMS CMK         (envelope encryption for tokens)
 *   - practices DDB table          (per-practice OAuth-adjacent config)
 *   - Lambda + Function URL        (the API itself)
 *   - IAM grants                   (RW on the above, plus connect:Search/Claim
 *                                   and secretsmanager:GetSecretValue on the
 *                                   PF client-secret ARN)
 *
 * Why Function URL vs API Gateway: the API has two public GETs and no
 * auth other than the state nonce baked into the OAuth flow itself.
 * Function URL keeps the surface minimal and HIPAA-eligible. API
 * Gateway lands in Session 0010+ when we add authenticated practice-
 * dashboard routes.
 */
export class ApiStack extends cdk.Stack {
  readonly handler: lambda.Function;
  readonly functionUrl: lambda.FunctionUrl;
  readonly stateTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const { envConfig, phoneRoutingTable, practicesTable, tokensTable,
            oauthKmsKey, connectInstanceId, connectInstanceArn,
            pfClientSecretArn } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    // ── oauth-state DDB (single-use PKCE state cache, TTL evicted) ───
    this.stateTable = new dynamodb.Table(this, "OAuthStateTable", {
      tableName: `${envConfig.resourcePrefix}-oauth-state`,
      partitionKey: { name: "state", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "ttl",
      removalPolicy: removal,
    });

    // ── Lambda + log group ───────────────────────────────────────────
    const logGroup = new logs.LogGroup(this, "OnboardingApiLogs", {
      logGroupName: `/aws/lambda/${envConfig.resourcePrefix}-onboarding-api`,
      retention: envConfig.logRetentionDays as logs.RetentionDays,
      removalPolicy: removal,
    });

    // Lambda code: bundled via ``pythonLambdaCode`` (Session 0010 —
    // resolves Session 0008 OQ #1). The asset contains the api
    // package + its local-package deps (oauth, routing, audit) +
    // their PyPI deps (fastapi, mangum, requests, ...). See
    // ``python-lambda-asset.ts`` for the bundling strategy.
    this.handler = new lambda.Function(this, "OnboardingApi", {
      functionName: `${envConfig.resourcePrefix}-onboarding-api`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: "api.handler.handler",
      code: pythonLambdaCode(["api", "oauth", "routing", "audit"]),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      logGroup,
      environment: {
        OAUTH_STATE_TABLE: this.stateTable.tableName,
        PRACTICES_TABLE: practicesTable.tableName,
        OAUTH_TOKENS_TABLE: tokensTable.tableName,
        OAUTH_TOKENS_KMS_KEY_ID: oauthKmsKey.keyId,
        PHONE_ROUTING_TABLE: phoneRoutingTable.tableName,
        CONNECT_INSTANCE_ID: connectInstanceId,
        CONNECT_INSTANCE_ARN: connectInstanceArn,
        OAUTH_REDIRECT_URI: props.oauthRedirectUri ?? "",
      },
    });

    // ── IAM grants ───────────────────────────────────────────────────
    this.stateTable.grantReadWriteData(this.handler);
    practicesTable.grantReadWriteData(this.handler);
    tokensTable.grantReadWriteData(this.handler);
    phoneRoutingTable.grantReadWriteData(this.handler);
    oauthKmsKey.grantEncryptDecrypt(this.handler);

    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "connect:SearchAvailablePhoneNumbersV2",
          "connect:ClaimPhoneNumber",
        ],
        resources: [connectInstanceArn, `${connectInstanceArn}/*`],
      }),
    );

    // Secrets Manager: read the global PF Provider App client secret.
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [pfClientSecretArn],
      }),
    );

    // ── Function URL ─────────────────────────────────────────────────
    this.functionUrl = this.handler.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      // GET-only API; CORS not needed (server-to-redirect flow).
    });

    new cdk.CfnOutput(this, "OnboardingApiUrl", {
      value: this.functionUrl.url,
    });
    new cdk.CfnOutput(this, "OAuthStateTableName", {
      value: this.stateTable.tableName,
    });
  }
}
