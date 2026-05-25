import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";

export interface RateLimitStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * Per-(practice, ANI) daily rate-limit table.
 *
 * One row per (practice_id#ani, YYYY-MM-DD) day-bucket. TTL on the
 * ``expires`` attribute auto-evicts rows ~48 h after their bucket
 * date, so the table stays bounded without manual cleanup.
 *
 * PAY_PER_REQUEST keeps small-volume billing trivial; provisioned
 * throughput is a Session-0016 (pilot cutover) decision if call
 * volume ever justifies it.
 */
export class RateLimitStack extends cdk.Stack {
  readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: RateLimitStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    this.table = new dynamodb.Table(this, "RateLimitTable", {
      tableName: `${envConfig.resourcePrefix}-rate-limit`,
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "bucket", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expires",
      removalPolicy: removal,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
    });

    new cdk.CfnOutput(this, "RateLimitTableName", { value: this.table.tableName });
  }
}
