import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

import { envs, loadEnv } from "../config/envs";
import { AuditStack } from "../lib/audit-stack";
import { RateLimitStack } from "../lib/rate-limit-stack";

describe("CDK app", () => {
  it("synthesizes without errors", () => {
    const app = new cdk.App();
    expect(() => app.synth()).not.toThrow();
  });
});

describe("envs config", () => {
  it("loads qa", () => {
    const cfg = loadEnv("qa");
    expect(cfg.account).toBe("000000000000");
    expect(cfg.resourcePrefix).toBe("pf-voice-qa");
  });

  it("rejects unknown env", () => {
    expect(() => loadEnv("dev")).toThrow(/qa\|staging\|prod/);
  });

  it("rejects TBD-account envs", () => {
    expect(() => loadEnv("staging")).toThrow(/no account provisioned/);
  });
});

describe("AuditStack (qa)", () => {
  const app = new cdk.App();
  const stack = new AuditStack(app, "pf-voice-qa-audit", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
  const t = Template.fromStack(stack);

  it("creates a KMS CMK with rotation enabled", () => {
    t.hasResourceProperties("AWS::KMS::Key", { EnableKeyRotation: true });
  });

  it("creates an S3 bucket with Object Lock + KMS encryption + public-access-block", () => {
    t.hasResourceProperties("AWS::S3::Bucket", {
      ObjectLockEnabled: true,
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          {
            ServerSideEncryptionByDefault: { SSEAlgorithm: "aws:kms" },
          },
        ],
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  it("Object Lock retention is 7 years, compliance mode", () => {
    t.hasResourceProperties("AWS::S3::Bucket", {
      ObjectLockConfiguration: {
        ObjectLockEnabled: "Enabled",
        Rule: {
          DefaultRetention: { Mode: "COMPLIANCE", Days: 7 * 365 },
        },
      },
    });
  });
});

describe("RateLimitStack (qa)", () => {
  const app = new cdk.App();
  const stack = new RateLimitStack(app, "pf-voice-qa-rate-limit", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
  const t = Template.fromStack(stack);

  it("creates a PAY_PER_REQUEST table partitioned by (pk, bucket) with TTL", () => {
    t.hasResourceProperties("AWS::DynamoDB::Table", {
      BillingMode: "PAY_PER_REQUEST",
      KeySchema: [
        { AttributeName: "pk", KeyType: "HASH" },
        { AttributeName: "bucket", KeyType: "RANGE" },
      ],
      TimeToLiveSpecification: { AttributeName: "expires", Enabled: true },
    });
  });
});

describe("removal policies differ by env", () => {
  it("prod retains, qa destroys", () => {
    expect(envs.prod.removalPolicy).toBe("RETAIN");
    expect(envs.qa.removalPolicy).toBe("DESTROY");
  });
});
