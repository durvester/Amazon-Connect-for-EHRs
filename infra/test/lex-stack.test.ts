import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { LexStack } from "../lib/lex-stack";

function buildStack(): cdk.Stack {
  const app = new cdk.App();
  return new LexStack(app, "pf-voice-qa-lex", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
    practicesTableName: "pf-voice-qa-practices",
    tokensTableName: "pf-voice-qa-oauth-tokens",
    oauthKmsKeyArn: "arn:aws:kms:us-east-1:000000000000:key/test-key-id",
    auditBucketName: "pf-voice-qa-audit",
    rateLimitTableName: "pf-voice-qa-rate-limit",
    practicesTableArn: "arn:aws:dynamodb:us-east-1:000000000000:table/pf-voice-qa-practices",
    tokensTableArn: "arn:aws:dynamodb:us-east-1:000000000000:table/pf-voice-qa-oauth-tokens",
    auditBucketArn: "arn:aws:s3:::pf-voice-qa-audit",
    auditKmsKeyArn: "arn:aws:kms:us-east-1:000000000000:key/test-audit-key-id",
    rateLimitTableArn: "arn:aws:dynamodb:us-east-1:000000000000:table/pf-voice-qa-rate-limit",
  });
}

describe("LexStack (qa) — ADR-0019 rewrite", () => {
  const t = Template.fromStack(buildStack());

  it("creates a Lex V2 bot", () => {
    t.resourceCountIs("AWS::Lex::Bot", 1);
    t.hasResourceProperties("AWS::Lex::Bot", {
      Name: "pf-voice-qa-verification",
      DataPrivacy: { ChildDirected: false },
    });
  });

  it("bot locale uses Nova 2 Sonic speech-to-speech", () => {
    t.hasResourceProperties("AWS::Lex::Bot", {
      BotLocales: Match.arrayWith([
        Match.objectLike({
          LocaleId: "en_US",
          UnifiedSpeechSettings: {
            SpeechFoundationModel: {
              ModelArn: Match.stringLikeRegexp("nova-2-sonic"),
              VoiceId: "Matthew",
            },
          },
        }),
      ]),
    });
  });

  it("bot has VerificationAgent + FallbackIntent — no rigid slots", () => {
    t.hasResourceProperties("AWS::Lex::Bot", {
      BotLocales: Match.arrayWith([
        Match.objectLike({
          Intents: Match.arrayWith([
            Match.objectLike({ Name: "VerificationAgent" }),
            Match.objectLike({
              Name: "FallbackIntent",
              ParentIntentSignature: "AMAZON.FallbackIntent",
              FulfillmentCodeHook: { Enabled: true },
            }),
          ]),
        }),
      ]),
    });
    const rendered = JSON.stringify(t.findResources("AWS::Lex::Bot"));
    expect(rendered).not.toMatch(/VerifyAndResolve/);
    expect(rendered).not.toMatch(/CallerFirstName/);
    expect(rendered).not.toMatch(/CallerLastName/);
    expect(rendered).not.toMatch(/DateOfBirth/);
  });

  it("creates a bot version and alias", () => {
    t.resourceCountIs("AWS::Lex::BotVersion", 1);
    t.resourceCountIs("AWS::Lex::BotAlias", 1);
  });

  it("bot alias has code-hook Lambda configured for en_US", () => {
    t.hasResourceProperties("AWS::Lex::BotAlias", {
      BotAliasLocaleSettings: Match.arrayWith([
        Match.objectLike({
          LocaleId: "en_US",
          BotAliasLocaleSetting: {
            Enabled: true,
            CodeHookSpecification: {
              LambdaCodeHook: {
                CodeHookInterfaceVersion: "1.0",
              },
            },
          },
        }),
      ]),
    });
  });

  it("creates a code-hook Lambda function with correct env vars", () => {
    t.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "pf-voice-qa-lex-code-hook",
      Runtime: "python3.12",
      Handler: "lex_code_hook.handler.handler",
      Environment: {
        Variables: Match.objectLike({
          PRACTICES_TABLE_NAME: "pf-voice-qa-practices",
          TOKENS_TABLE_NAME: "pf-voice-qa-oauth-tokens",
          BEDROCK_MODEL_ID: Match.stringLikeRegexp("claude"),
        }),
      },
    });
  });

  it("Lex bot role has bedrock invoke permissions for Nova 2 Sonic", () => {
    const policies = t.findResources("AWS::IAM::Policy");
    const rendered = JSON.stringify(policies);
    expect(rendered).toMatch(/bedrock:InvokeModelWithBidirectionalStream/);
    expect(rendered).toMatch(/nova-2-sonic/);
  });

  it("code-hook Lambda has bedrock invoke permission for Claude", () => {
    const policies = t.findResources("AWS::IAM::Policy");
    const rendered = JSON.stringify(policies);
    expect(rendered).toMatch(/bedrock:InvokeModel/);
  });

  it("code-hook Lambda has DDB, KMS, S3, SecretsManager permissions", () => {
    const policies = t.findResources("AWS::IAM::Policy");
    const rendered = JSON.stringify(policies);
    expect(rendered).toMatch(/dynamodb:GetItem/);
    expect(rendered).toMatch(/kms:Decrypt/);
    expect(rendered).toMatch(/s3:PutObject/);
    expect(rendered).toMatch(/secretsmanager:GetSecretValue/);
  });

  it("exposes bot alias ARN and code-hook Lambda ARN outputs", () => {
    t.hasOutput("BotId", {});
    t.hasOutput("BotAliasId", {});
    t.hasOutput("BotAliasArn", {});
    t.hasOutput("CodeHookLambdaArn", {});
  });
});
