import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";

export interface PhoneRoutingStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * DID → practice_id resolver table (ADR-0014).
 *
 * Read at every inbound call by the Connect contact flow's native
 * `InvokeAWSService` DDB integration; written by the OAuth onboarding
 * API (Session 0008) when a practice completes onboarding.
 *
 * One row per claimed DID. Released DIDs stay in the table with
 * ``status="released"`` for audit purposes — call-path reads filter
 * to active only.
 *
 * PAY_PER_REQUEST because we expect light read volume (one GetItem per
 * call) and write-on-onboarding. PITR enabled in prod (the table is
 * small and the data is the canonical multi-tenancy router — losing
 * it would break every inbound call).
 */
export class PhoneRoutingStack extends cdk.Stack {
  readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: PhoneRoutingStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    this.table = new dynamodb.Table(this, "PhoneRoutingTable", {
      tableName: `${envConfig.resourcePrefix}-phone-routing`,
      partitionKey: {
        name: "phone_number",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: removal,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
    });

    new cdk.CfnOutput(this, "PhoneRoutingTableName", {
      value: this.table.tableName,
    });
    new cdk.CfnOutput(this, "PhoneRoutingTableArn", {
      value: this.table.tableArn,
    });
  }
}
