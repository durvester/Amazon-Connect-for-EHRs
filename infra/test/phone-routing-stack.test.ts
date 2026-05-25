import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { PhoneRoutingStack } from "../lib/phone-routing-stack";

describe("PhoneRoutingStack (qa)", () => {
  const app = new cdk.App();
  const stack = new PhoneRoutingStack(app, "pf-voice-qa-phone-routing", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
  const t = Template.fromStack(stack);

  it("creates a PAY_PER_REQUEST table partitioned by phone_number", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-phone-routing",
      BillingMode: "PAY_PER_REQUEST",
      KeySchema: [{ AttributeName: "phone_number", KeyType: "HASH" }],
      AttributeDefinitions: Match.arrayWith([
        { AttributeName: "phone_number", AttributeType: "S" },
      ]),
    });
  });

  it("disables PITR in qa", () => {
    // ADR-0014: phone_routing is durable but small. PITR carries cost
    // and is reserved for prod (matches RateLimitStack convention).
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: false },
    });
  });

  it("uses env-suffixed resource name per ADR-0008", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: Match.stringLikeRegexp("^pf-voice-qa-"),
    });
  });

  it("exposes the table name as an output", () => {
    t.hasOutput("PhoneRoutingTableName", {});
  });
});

describe("PhoneRoutingStack (prod) — PITR + retain", () => {
  const app = new cdk.App();
  const prodLike = {
    ...envs.prod,
    account: "111122223333", // synth needs a non-TBD account here
  };
  const stack = new PhoneRoutingStack(app, "pf-voice-prod-phone-routing", {
    env: { account: prodLike.account, region: prodLike.region },
    envConfig: prodLike,
  });
  const t = Template.fromStack(stack);

  it("enables PITR in prod", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
    });
  });

  it("retains the table in prod", () => {
    t.hasResource("AWS::DynamoDB::Table", { DeletionPolicy: "Retain" });
  });
});
