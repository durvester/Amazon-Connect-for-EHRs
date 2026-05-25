import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { PracticesStack } from "../lib/practices-stack";

function buildStack(): cdk.Stack {
  const app = new cdk.App();
  return new PracticesStack(app, "pf-voice-qa-practices", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
}

describe("PracticesStack (qa)", () => {
  const t = Template.fromStack(buildStack());

  it("creates a practices DDB table with practice_id PK", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-practices",
      KeySchema: Match.arrayWith([
        { AttributeName: "practice_id", KeyType: "HASH" },
      ]),
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  it("creates an oauth-tokens DDB table with practice_id PK", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-oauth-tokens",
      KeySchema: Match.arrayWith([
        { AttributeName: "practice_id", KeyType: "HASH" },
      ]),
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  it("creates a KMS CMK for OAuth token encryption", () => {
    t.resourceCountIs("AWS::KMS::Key", 1);
    t.hasResourceProperties("AWS::KMS::Key", {
      EnableKeyRotation: true,
    });
  });

  it("tokens table uses CMK encryption", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-oauth-tokens",
      SSESpecification: Match.objectLike({
        SSEEnabled: true,
      }),
    });
  });

  it("exposes table names and ARNs as outputs", () => {
    t.hasOutput("PracticesTableName", {});
    t.hasOutput("PracticesTableArn", {});
    t.hasOutput("TokensTableName", {});
    t.hasOutput("TokensTableArn", {});
    t.hasOutput("OAuthKeyArn", {});
  });
});
