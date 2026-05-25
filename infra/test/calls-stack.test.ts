import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { CallsStack } from "../lib/calls-stack";

function build() {
  const app = new cdk.App();
  const stack = new CallsStack(app, "pf-voice-qa-calls", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
  return Template.fromStack(stack);
}

describe("CallsStack (qa)", () => {
  it("creates a calls table with practice_id PK and call_id SK", () => {
    const t = build();
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "pf-voice-qa-calls",
      KeySchema: [
        { AttributeName: "practice_id", KeyType: "HASH" },
        { AttributeName: "call_id", KeyType: "RANGE" },
      ],
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  it("has a TTL attribute for auto-expiry", () => {
    const t = build();
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      TimeToLiveSpecification: { AttributeName: "ttl", Enabled: true },
    });
  });

  it("has a by-started-at GSI for time-range queries", () => {
    const t = build();
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({
          IndexName: "by-started-at",
          KeySchema: [
            { AttributeName: "practice_id", KeyType: "HASH" },
            { AttributeName: "started_at", KeyType: "RANGE" },
          ],
        }),
      ]),
    });
  });

  it("has DynamoDB streams enabled for future dashboard", () => {
    const t = build();
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      StreamSpecification: { StreamViewType: "NEW_IMAGE" },
    });
  });
});
