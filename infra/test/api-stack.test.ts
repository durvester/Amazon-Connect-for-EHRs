import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as kms from "aws-cdk-lib/aws-kms";

import { envs } from "../config/envs";
import { ApiStack } from "../lib/api-stack";

const PF_CLIENT_SECRET_ARN =
  "arn:aws:secretsmanager:us-east-1:000000000000:secret:pf-voice-qa-pf-client-secret";
const INSTANCE_ID = "11111111-2222-3333-4444-555555555555";
const INSTANCE_ARN = `arn:aws:connect:us-east-1:000000000000:instance/${INSTANCE_ID}`;

function build() {
  const app = new cdk.App();
  const fixtureStack = new cdk.Stack(app, "Fixtures", {
    env: { account: envs.qa.account, region: envs.qa.region },
  });
  const phoneRoutingTable = dynamodb.Table.fromTableName(
    fixtureStack, "PhoneRouting", "pf-voice-qa-phone-routing",
  );
  const practicesTable = dynamodb.Table.fromTableName(
    fixtureStack, "Practices", "pf-voice-qa-practices",
  );
  const tokensTable = dynamodb.Table.fromTableName(
    fixtureStack, "Tokens", "pf-voice-qa-oauth-tokens",
  );
  const oauthKmsKey = kms.Key.fromKeyArn(
    fixtureStack, "OAuthKey",
    "arn:aws:kms:us-east-1:000000000000:key/test-key-id",
  );

  const stack = new ApiStack(app, "pf-voice-qa-api", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
    phoneRoutingTable,
    practicesTable,
    tokensTable,
    oauthKmsKey,
    connectInstanceId: INSTANCE_ID,
    connectInstanceArn: INSTANCE_ARN,
    pfClientSecretArn: PF_CLIENT_SECRET_ARN,
  });
  return Template.fromStack(stack);
}

describe("ApiStack (qa)", () => {
  it("creates the oauth-state table with TTL on the `ttl` attribute", () => {
    const t = build();
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-oauth-state",
      KeySchema: [{ AttributeName: "state", KeyType: "HASH" }],
      BillingMode: "PAY_PER_REQUEST",
      TimeToLiveSpecification: { AttributeName: "ttl", Enabled: true },
    });
  });

  it("does not create practices or tokens tables (owned by PracticesStack)", () => {
    const t = build();
    const tables = t.findResources("AWS::DynamoDB::Table");
    const tableNames = Object.values(tables).map(
      (r: any) => r.Properties?.TableName,
    );
    expect(tableNames).not.toContain("pf-voice-qa-practices");
    expect(tableNames).not.toContain("pf-voice-qa-oauth-tokens");
  });

  it("creates the Python 3.12 Lambda with the right env wiring", () => {
    const t = build();
    t.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "pf-voice-qa-onboarding-api",
      Runtime: "python3.12",
      Handler: "api.handler.handler",
      Environment: {
        Variables: Match.objectLike({
          // Most table names are CFN tokens (Ref) — we assert the
          // *keys* are wired; literal values are checked above by
          // hasResourceProperties on the table resources themselves.
          PHONE_ROUTING_TABLE: "pf-voice-qa-phone-routing",
          CONNECT_INSTANCE_ID: INSTANCE_ID,
          CONNECT_INSTANCE_ARN: INSTANCE_ARN,
          OAUTH_STATE_TABLE: Match.anyValue(),
          PRACTICES_TABLE: Match.anyValue(),
          OAUTH_TOKENS_TABLE: Match.anyValue(),
          OAUTH_TOKENS_KMS_KEY_ID: Match.anyValue(),
        }),
      },
    });
  });

  it("grants connect:Search + Claim and secretsmanager:GetSecretValue on the PF secret", () => {
    const t = build();
    t.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: [
              "connect:SearchAvailablePhoneNumbersV2",
              "connect:ClaimPhoneNumber",
            ],
            Effect: "Allow",
            Resource: "*",
          }),
          Match.objectLike({
            Action: "secretsmanager:GetSecretValue",
            Effect: "Allow",
            Resource: PF_CLIENT_SECRET_ARN,
          }),
        ]),
      }),
    });
  });

  it("publishes a Function URL", () => {
    const t = build();
    t.hasResourceProperties("AWS::Lambda::Url", {
      AuthType: "NONE",
    });
    t.hasOutput("OnboardingApiUrl", {});
  });
});
