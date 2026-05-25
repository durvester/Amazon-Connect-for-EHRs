import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as kms from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";

export interface PracticesStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * Practice configuration + OAuth token storage (ADR-0020).
 *
 * Two DDB tables keyed by pf_org_uuid (the PF canonical practice GUID):
 *   - practices: per-practice FHIR config (base URL, client ID, etc.)
 *   - oauth-tokens: KMS-encrypted access/refresh tokens
 *
 * One KMS CMK (oauth-key) encrypts token ciphertext at the app layer.
 * DDB SSE-KMS adds at-rest encryption on top.
 */
export class PracticesStack extends cdk.Stack {
  readonly practicesTable: dynamodb.Table;
  readonly tokensTable: dynamodb.Table;
  readonly oauthKey: kms.Key;

  constructor(scope: Construct, id: string, props: PracticesStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    // -- KMS CMK for OAuth token encryption --
    this.oauthKey = new kms.Key(this, "OAuthKey", {
      alias: `${envConfig.resourcePrefix}-oauth-key`,
      description: `KMS CMK for ${envConfig.envName} OAuth token encryption`,
      enableKeyRotation: true,
      removalPolicy: removal,
    });

    // -- Practices table (ADR-0020: pf_org_uuid as PK) --
    this.practicesTable = new dynamodb.Table(this, "PracticesTable", {
      tableName: `${envConfig.resourcePrefix}-practices`,
      partitionKey: {
        name: "practice_id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: removal,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
    });

    // -- OAuth tokens table (ADR-0020: pf_org_uuid as PK) --
    this.tokensTable = new dynamodb.Table(this, "TokensTable", {
      tableName: `${envConfig.resourcePrefix}-oauth-tokens`,
      partitionKey: {
        name: "practice_id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: this.oauthKey,
      removalPolicy: removal,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: envConfig.envName === "prod",
      },
    });

    // -- Outputs --
    new cdk.CfnOutput(this, "PracticesTableName", {
      value: this.practicesTable.tableName,
    });
    new cdk.CfnOutput(this, "PracticesTableArn", {
      value: this.practicesTable.tableArn,
    });
    new cdk.CfnOutput(this, "TokensTableName", {
      value: this.tokensTable.tableName,
    });
    new cdk.CfnOutput(this, "TokensTableArn", {
      value: this.tokensTable.tableArn,
    });
    new cdk.CfnOutput(this, "OAuthKeyArn", {
      value: this.oauthKey.keyArn,
    });
  }
}
