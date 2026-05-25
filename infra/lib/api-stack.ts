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
  readonly connectInstanceId: string;
  readonly connectInstanceArn: string;
  /**
   * The global PF Provider App client secret ARN (one app per
   * environment, shared across all practices). Per-practice rows in
   * the practices table reference this same ARN until/unless we
   * decide multiple PF apps are needed.
   */
  readonly pfClientSecretArn: string;
  /**
   * The fully-qualified ``/oauth/callback`` URL PF will 302 to. Empty
   * on the first deploy (the Function URL only materializes once the
   * stack lands); on the second deploy this is set to the actual
   * Function URL captured from CFN outputs. The api Lambda fails
   * closed if this is empty when ``/oauth/start`` is invoked.
   */
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
  readonly tokensTable: dynamodb.Table;
  readonly tokensKey: kms.Key;
  readonly practicesTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const { envConfig, phoneRoutingTable, connectInstanceId, connectInstanceArn,
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
      // No PITR — these rows live for minutes; abandoned ones are noise.
    });

    // ── oauth-tokens KMS CMK ─────────────────────────────────────────
    this.tokensKey = new kms.Key(this, "OAuthTokensKey", {
      description: `${envConfig.resourcePrefix} OAuth token envelope-encryption CMK`,
      enableKeyRotation: true,
      removalPolicy: removal,
      alias: `alias/${envConfig.resourcePrefix}-oauth-tokens`,
    });

    // ── oauth-tokens DDB ─────────────────────────────────────────────
    this.tokensTable = new dynamodb.Table(this, "OAuthTokensTable", {
      tableName: `${envConfig.resourcePrefix}-oauth-tokens`,
      partitionKey: { name: "practice_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: removal,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: this.tokensKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
    });

    // ── practices DDB (OAuth-adjacent config) ────────────────────────
    // Architecture doc lists additional non-OAuth fields (queue ARN,
    // verification factors, …) added by later sessions. This stack
    // owns the table; subsequent sessions ALTER attributes only.
    this.practicesTable = new dynamodb.Table(this, "PracticesTable", {
      tableName: `${envConfig.resourcePrefix}-practices`,
      partitionKey: { name: "practice_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: removal,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
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
        PRACTICES_TABLE: this.practicesTable.tableName,
        OAUTH_TOKENS_TABLE: this.tokensTable.tableName,
        OAUTH_TOKENS_KMS_KEY_ID: this.tokensKey.keyId,
        PHONE_ROUTING_TABLE: phoneRoutingTable.tableName,
        CONNECT_INSTANCE_ID: connectInstanceId,
        CONNECT_INSTANCE_ARN: connectInstanceArn,
        // Wired from the ``oauthRedirectUri`` prop (CDK context
        // ``oauthRedirectUri=<url>``). Empty on first deploy because
        // the Function URL only materializes after stack creation;
        // the second deploy passes the real URL.
        OAUTH_REDIRECT_URI: props.oauthRedirectUri ?? "",
      },
    });

    // ── IAM grants ───────────────────────────────────────────────────
    this.stateTable.grantReadWriteData(this.handler);
    this.practicesTable.grantReadWriteData(this.handler);
    this.tokensTable.grantReadWriteData(this.handler);
    phoneRoutingTable.grantReadWriteData(this.handler);
    this.tokensKey.grantEncryptDecrypt(this.handler);

    // Connect: search + claim DIDs against any phone number in the
    // account. The action surface intentionally excludes ReleaseChannel.
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "connect:SearchAvailablePhoneNumbersV2",
          "connect:ClaimPhoneNumber",
        ],
        resources: ["*"],
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
    new cdk.CfnOutput(this, "PracticesTableName", {
      value: this.practicesTable.tableName,
    });
    new cdk.CfnOutput(this, "OAuthTokensTableName", {
      value: this.tokensTable.tableName,
    });
    new cdk.CfnOutput(this, "OAuthTokensKeyId", {
      value: this.tokensKey.keyId,
    });
  }
}
