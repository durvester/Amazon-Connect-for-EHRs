import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as lex from "aws-cdk-lib/aws-lex";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";
import { pythonLambdaCode } from "./python-lambda-asset";

export interface LexStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
  readonly practicesTableName: string;
  readonly tokensTableName: string;
  readonly oauthKmsKeyArn: string;
  readonly auditBucketName: string;
  readonly rateLimitTableName: string;
  readonly practicesTableArn: string;
  readonly tokensTableArn: string;
  readonly auditBucketArn: string;
  readonly auditKmsKeyArn: string;
  readonly rateLimitTableArn: string;
  readonly callsTableName?: string;
  readonly callsTableArn?: string;
}

/**
 * Lex V2 bot with Nova 2 Sonic speech-to-speech (ADR-0018 + ADR-0019).
 *
 * ADR-0019 rewrite: single FallbackIntent + fulfillmentCodeHook. No slots,
 * no VerifyAndResolve intent. The code-hook Lambda calls Claude every turn
 * for natural conversation. Nova 2 Sonic handles speech I/O only.
 */
export class LexStack extends cdk.Stack {
  readonly botAliasArn: string;
  readonly codeHookLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: LexStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    const botName = `${envConfig.resourcePrefix}-verification`;

    // -- Lex bot service role --
    const botRole = new iam.Role(this, "LexBotRole", {
      roleName: `${envConfig.resourcePrefix}-lex-bot-role`,
      assumedBy: new iam.ServicePrincipal("lexv2.amazonaws.com"),
    });
    botRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokeNovaSonic",
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithBidirectionalStream",
        ],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.nova-2-sonic-v1:0`,
        ],
      }),
    );

    // -- Code-hook Lambda --
    const codeHookLogGroup = new logs.LogGroup(this, "CodeHookLogs", {
      logGroupName: `/aws/lambda/${envConfig.resourcePrefix}-lex-code-hook`,
      retention: envConfig.logRetentionDays as logs.RetentionDays,
      removalPolicy: removal,
    });

    this.codeHookLambda = new lambda.Function(this, "CodeHookHandler", {
      functionName: `${envConfig.resourcePrefix}-lex-code-hook`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: "lex_code_hook.handler.handler",
      code: pythonLambdaCode([
        "tools/lex_code_hook",
        "tools/lookup_patient",
        "tools/fhir_query",
        "oauth",
        "audit",
        "routing",
      ]),
      timeout: cdk.Duration.seconds(25),
      memorySize: 512,
      logGroup: codeHookLogGroup,
      environment: {
        PRACTICES_TABLE_NAME: props.practicesTableName,
        TOKENS_TABLE_NAME: props.tokensTableName,
        OAUTH_KMS_KEY_ARN: props.oauthKmsKeyArn,
        AUDIT_BUCKET_NAME: props.auditBucketName,
        RATELIMIT_TABLE_NAME: props.rateLimitTableName,
        BEDROCK_MODEL_ID: "us.anthropic.claude-sonnet-4-6",
        ...(props.callsTableName && { CALLS_TABLE_NAME: props.callsTableName }),
      },
    });

    // Grant code-hook Lambda access to DDB tables, KMS, S3, Bedrock
    this.codeHookLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
        resources: [
          props.practicesTableArn,
          props.tokensTableArn,
          props.rateLimitTableArn,
          ...(props.callsTableArn ? [props.callsTableArn] : []),
        ],
      }),
    );
    this.codeHookLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"],
        resources: [props.oauthKmsKeyArn, props.auditKmsKeyArn],
      }),
    );
    this.codeHookLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [`${props.auditBucketArn}/*`],
      }),
    );
    this.codeHookLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/anthropic.*`,
          `arn:aws:bedrock:${this.region}::foundation-model/us.anthropic.*`,
        ],
      }),
    );
    this.codeHookLambda.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${envConfig.resourcePrefix}-*`,
        ],
      }),
    );

    // -- Lex Bot (ADR-0019: FallbackIntent only, no slots) --
    const novaSonicModelArn = `arn:aws:bedrock:${this.region}::foundation-model/amazon.nova-2-sonic-v1:0`;

    const bot = new lex.CfnBot(this, "VerificationBot", {
      name: botName,
      roleArn: botRole.roleArn,
      dataPrivacy: { ChildDirected: false },
      idleSessionTtlInSeconds: 300,
      autoBuildBotLocales: true,
      botLocales: [
        {
          localeId: "en_US",
          nluConfidenceThreshold: 0.4,
          unifiedSpeechSettings: {
            speechFoundationModel: {
              modelArn: novaSonicModelArn,
              voiceId: "Matthew",
            },
          },
          intents: [
            {
              name: "VerificationAgent",
              description:
                "Primary intent: routes all caller speech to the code-hook Lambda. " +
                "Lex requires at least one custom intent with utterances to build the locale.",
              sampleUtterances: [
                { utterance: "hello" },
                { utterance: "I need help" },
                { utterance: "hi there" },
                { utterance: "I am calling about my results" },
                { utterance: "good morning" },
              ],
              fulfillmentCodeHook: { enabled: true },
            },
            {
              name: "FallbackIntent",
              parentIntentSignature: "AMAZON.FallbackIntent",
              fulfillmentCodeHook: { enabled: true },
            },
          ],
        },
      ],
    });
    bot.applyRemovalPolicy(removal);

    const botVersion = new lex.CfnBotVersion(this, "BotVersion", {
      botId: bot.attrId,
      botVersionLocaleSpecification: [
        {
          localeId: "en_US",
          botVersionLocaleDetails: {
            sourceBotVersion: "DRAFT",
          },
        },
      ],
    });
    botVersion.addDependency(bot);

    const botAlias = new lex.CfnBotAlias(this, "BotAlias", {
      botId: bot.attrId,
      botAliasName: `${envConfig.resourcePrefix}-live`,
      botVersion: botVersion.attrBotVersion,
      botAliasLocaleSettings: [
        {
          localeId: "en_US",
          botAliasLocaleSetting: {
            enabled: true,
            codeHookSpecification: {
              lambdaCodeHook: {
                codeHookInterfaceVersion: "1.0",
                lambdaArn: this.codeHookLambda.functionArn,
              },
            },
          },
        },
      ],
    });
    botAlias.applyRemovalPolicy(removal);

    this.botAliasArn = `arn:aws:lex:${this.region}:${this.account}:bot-alias/${bot.attrId}/${botAlias.attrBotAliasId}`;

    this.codeHookLambda.addPermission("LexInvoke", {
      principal: new iam.ServicePrincipal("lexv2.amazonaws.com"),
      sourceArn: this.botAliasArn,
    });

    // -- Outputs --
    new cdk.CfnOutput(this, "BotId", { value: bot.attrId });
    new cdk.CfnOutput(this, "BotAliasId", {
      value: botAlias.attrBotAliasId,
    });
    new cdk.CfnOutput(this, "BotAliasArn", { value: this.botAliasArn });
    new cdk.CfnOutput(this, "CodeHookLambdaArn", {
      value: this.codeHookLambda.functionArn,
    });
  }
}
