import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";

export interface AuditStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * S3 audit-log bucket + dedicated KMS CMK.
 *
 * Object Lock (compliance mode, 7-year retention) makes records
 * tamper-evident: nothing — not even the root account — can delete or
 * overwrite an object inside the lock window. KMS-CMK gives both
 * encryption at rest and a key-policy gate for who can read.
 *
 * Writers: lookup_patient (Session 0006) and every future tool that
 * reads PHI. Readers: the dedicated compliance role only (granted in
 * Session 0016 — pilot cutover prep).
 *
 * Synth-only this session. Deploy lands in Session 0007 alongside the
 * Connect/AgentCore spike.
 */
export class AuditStack extends cdk.Stack {
  readonly bucket: s3.Bucket;
  readonly kmsKey: kms.Key;

  constructor(scope: Construct, id: string, props: AuditStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    this.kmsKey = new kms.Key(this, "AuditKey", {
      alias: `${envConfig.resourcePrefix}-audit-key`,
      description: `KMS CMK for ${envConfig.envName} HIPAA disclosure audit records`,
      enableKeyRotation: true,
      removalPolicy: removal,
    });

    this.bucket = new s3.Bucket(this, "AuditBucket", {
      bucketName: `${envConfig.resourcePrefix}-audit`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.kmsKey,
      enforceSSL: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      // Object Lock = "no delete / overwrite within retention window."
      // Compliance mode means even the root user cannot bypass it.
      objectLockEnabled: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.compliance(
        cdk.Duration.days(7 * 365),
      ),
      versioned: true,
      removalPolicy: removal,
      autoDeleteObjects: false, // Object Lock blocks deletion regardless of env
    });

    new cdk.CfnOutput(this, "AuditBucketName", { value: this.bucket.bucketName });
    new cdk.CfnOutput(this, "AuditKmsKeyArn", { value: this.kmsKey.keyArn });
  }
}
