import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";

export interface CallsStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * Call metadata store (Session 0014).
 *
 * One row per completed call. Written by the code-hook Lambda on Close.
 * No PHI — only call metadata (practice_id, call_id, outcome, timestamps).
 *
 * PK: practice_id, SK: call_id.
 * GSI: practice_id + started_at for time-range queries (dashboard).
 * TTL: auto-expire after 90 days.
 */
export class CallsStack extends cdk.Stack {
  readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: CallsStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    this.table = new dynamodb.Table(this, "CallsTable", {
      tableName: `${envConfig.resourcePrefix}-calls`,
      partitionKey: {
        name: "practice_id",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "call_id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "ttl",
      removalPolicy: removal,
      stream: dynamodb.StreamViewType.NEW_IMAGE,
    });

    this.table.addGlobalSecondaryIndex({
      indexName: "by-started-at",
      partitionKey: {
        name: "practice_id",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "started_at",
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, "CallsTableName", {
      value: this.table.tableName,
    });
    new cdk.CfnOutput(this, "CallsTableArn", {
      value: this.table.tableArn,
    });
  }
}
