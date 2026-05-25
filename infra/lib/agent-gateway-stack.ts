import * as cdk from "aws-cdk-lib";
import * as agentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";
import * as path from "path";

import type { EnvConfig } from "../config/envs";
import { pythonLambdaCode } from "./python-lambda-asset";

export interface AgentGatewayStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
}

/**
 * Bedrock AgentCore Gateway + one Lambda Target per tool (ADR-0012).
 *
 * The Gateway is the single MCP-tool catalog for every consumer of our
 * FHIR tools: today's Connect AI agent, plus any future MCP client (PF
 * chat surface, internal staff dashboards). Each tool ships with a
 * Lambda + a ``tool_schema.json`` file co-located in ``tools/<tool>/``.
 *
 * Session 0007 lands one Target: ``lookup_patient``. Sessions 0010–0012
 * register the lab-status, visit-summary, and document-status Targets
 * using the same pattern.
 *
 * Gateway naming: AgentCore Gateway names must match
 * ``^[a-zA-Z][a-zA-Z0-9_]{0,47}$`` (underscores, no hyphens). We use
 * ``pf_voice_<env>_gw`` rather than the hyphenated resourcePrefix.
 */
export class AgentGatewayStack extends cdk.Stack {
  readonly gateway: agentcore.Gateway;
  readonly lookupPatient: lambda.Function;

  constructor(scope: Construct, id: string, props: AgentGatewayStackProps) {
    super(scope, id, props);

    const { envConfig } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    // AgentCore Gateway names accept hyphens but not underscores at
    // runtime (despite the type declaration's looser hint).
    const gwName = `${envConfig.resourcePrefix}-gw`;

    // ── lookup_patient Lambda ────────────────────────────────────────
    // The handler is `lookup_patient.handler.handler` after the slim
    // refactor (ADR-0013). Code asset is the tool's src/ directory.
    const lookupLogGroup = new logs.LogGroup(this, "LookupPatientLogs", {
      logGroupName: `/aws/lambda/${envConfig.resourcePrefix}-lookup-patient`,
      retention: envConfig.logRetentionDays as logs.RetentionDays,
      removalPolicy: removal,
    });

    this.lookupPatient = new lambda.Function(this, "LookupPatientHandler", {
      functionName: `${envConfig.resourcePrefix}-lookup-patient`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: "lookup_patient.handler.handler",
      code: pythonLambdaCode(["tools/lookup_patient", "oauth", "audit"]),
      timeout: cdk.Duration.seconds(25), // 5 s headroom under Gateway's 30 s limit (ADR-0012)
      memorySize: 512,
      logGroup: lookupLogGroup,
      environment: {
        // Cross-stack table-name handoff lands in Session 0008+; for the
        // session-0007 skeleton the Lambda runs with empty env and will
        // fail closed in production until Session 0008 wires real values.
        // Tests don't exercise the deployed Lambda — only the synth + the
        // local unit suite that injects mocked stores.
        PF_PRACTICES_TABLE: "",
        PF_TOKEN_TABLE: "",
        PF_RATE_LIMIT_TABLE: "",
        PF_PHONE_ROUTING_TABLE: "",
        PF_AUDIT_BUCKET: "",
        PF_TOKEN_KMS_KEY_ARN: "",
      },
    });

    // ── Gateway ──────────────────────────────────────────────────────
    this.gateway = new agentcore.Gateway(this, "Gateway", {
      gatewayName: gwName,
      description: `MCP tool catalog for ${envConfig.envName} (ADR-0012)`,
    });
    this.gateway.applyRemovalPolicy(removal);

    // ── lookup_patient Target ────────────────────────────────────────
    // ToolSchema is loaded from the file co-located with the tool's
    // source — single source of truth for inputs/outputs (ADR-0012).
    this.gateway.addLambdaTarget("LookupPatientTarget", {
      gatewayTargetName: "lookup-patient",
      description:
        "Search PF FHIR Patient resources for verification; returns candidates (ADR-0013).",
      lambdaFunction: this.lookupPatient,
      toolSchema: agentcore.ToolSchema.fromLocalAsset(
        path.join(
          __dirname,
          "..",
          "..",
          "tools",
          "lookup_patient",
          "tool_schema.json",
        ),
      ),
    });

    // ── Outputs ──────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "GatewayId", {
      value: this.gateway.gatewayId,
    });
    new cdk.CfnOutput(this, "GatewayArn", {
      value: this.gateway.gatewayArn,
    });
    new cdk.CfnOutput(this, "LookupPatientLambdaArn", {
      value: this.lookupPatient.functionArn,
    });
  }
}
