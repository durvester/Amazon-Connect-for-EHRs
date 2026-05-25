import * as cdk from "aws-cdk-lib";
import * as connect from "aws-cdk-lib/aws-connect";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

import type { EnvConfig } from "../config/envs";
import { pythonLambdaCode } from "./python-lambda-asset";

export interface ConnectStackProps extends cdk.StackProps {
  readonly envConfig: EnvConfig;
  readonly phoneRoutingTable: dynamodb.ITable;
  readonly lexBotAliasArn: string;
  readonly escalationQueueArn?: string;
}

/**
 * Amazon Connect instance + verification contact flow (ADR-0018, ADR-0020).
 *
 * Flow: InvokeLambdaFunction (router) → UpdateContactAttributes →
 *   ConnectParticipantWithLexBot → DisconnectParticipant
 */
export class ConnectStack extends cdk.Stack {
  readonly connectInstance: connect.CfnInstance;
  readonly verificationFlow: connect.CfnContactFlow;
  readonly routerLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: ConnectStackProps) {
    super(scope, id, props);

    const { envConfig, phoneRoutingTable, lexBotAliasArn, escalationQueueArn } = props;
    const removal =
      envConfig.removalPolicy === "DESTROY"
        ? cdk.RemovalPolicy.DESTROY
        : cdk.RemovalPolicy.RETAIN;

    // -- Connect instance --
    const alias = `${envConfig.resourcePrefix}-${cdk.Stack.of(this).account}`;
    this.connectInstance = new connect.CfnInstance(this, "ConnectInstance", {
      identityManagementType: "CONNECT_MANAGED",
      instanceAlias: alias,
      attributes: {
        inboundCalls: true,
        outboundCalls: false,
        contactflowLogs: true,
      },
    });
    this.connectInstance.applyRemovalPolicy(removal);

    // -- Router Lambda (ADR-0014 + ADR-0018 + ADR-0020) --
    const routerLogGroup = new logs.LogGroup(this, "RouterLogs", {
      logGroupName: `/aws/lambda/${envConfig.resourcePrefix}-router`,
      retention: envConfig.logRetentionDays as logs.RetentionDays,
      removalPolicy: removal,
    });

    this.routerLambda = new lambda.Function(this, "RouterHandler", {
      functionName: `${envConfig.resourcePrefix}-router`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: "router_lookup.handler.handler",
      code: pythonLambdaCode(["tools/router_lookup"]),
      timeout: cdk.Duration.seconds(5),
      memorySize: 256,
      logGroup: routerLogGroup,
      environment: {
        PF_PHONE_ROUTING_TABLE: phoneRoutingTable.tableName,
      },
    });
    phoneRoutingTable.grantReadData(this.routerLambda);

    this.routerLambda.addPermission("ConnectInvoke", {
      principal: new iam.ServicePrincipal("connect.amazonaws.com"),
      sourceArn: this.connectInstance.attrArn,
    });

    // -- Contact flow (ADR-0020: pf_org_uuid) --
    const postLexAction = escalationQueueArn ? "check-escalation" : "disconnect";

    const actions: object[] = [
        {
          Identifier: "router-invoke",
          Type: "InvokeLambdaFunction",
          Parameters: {
            LambdaFunctionARN: this.routerLambda.functionArn,
            InvocationTimeLimitSeconds: "5",
            ResponseValidation: { ResponseType: "STRING_MAP" },
          },
          Transitions: {
            NextAction: "set-attrs",
            Errors: [
              { NextAction: "play-error", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "set-attrs",
          Type: "UpdateContactAttributes",
          Parameters: {
            Attributes: {
              pf_org_uuid: "$.External.pf_org_uuid",
            },
          },
          Transitions: {
            NextAction: "lex-handoff",
            Errors: [
              { NextAction: "play-error", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "lex-handoff",
          Type: "ConnectParticipantWithLexBot",
          Parameters: {
            Text: "One moment while I look up your account.",
            LexV2Bot: {
              AliasArn: lexBotAliasArn,
            },
            LexSessionAttributes: {
              pf_org_uuid: "$.Attributes.pf_org_uuid",
              caller_phone: "$.CustomerEndpoint.Address",
              call_id: "$.ContactId",
            },
          },
          Transitions: {
            NextAction: postLexAction,
            Errors: [
              { NextAction: "play-lex-error", ErrorType: "NoMatchingError" },
              { NextAction: "play-done", ErrorType: "NoMatchingCondition" },
              { NextAction: "play-lex-error", ErrorType: "InputTimeLimitExceeded" },
            ],
          },
        },
        {
          Identifier: "play-done",
          Type: "MessageParticipant",
          Parameters: {
            Text: "The AI conversation has ended. Thank you for calling. Goodbye.",
          },
          Transitions: {
            NextAction: "disconnect",
            Errors: [
              { NextAction: "disconnect", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "play-lex-error",
          Type: "MessageParticipant",
          Parameters: {
            Text: "Sorry, there was a problem connecting to the AI agent. Please try again later. Goodbye.",
          },
          Transitions: {
            NextAction: "disconnect",
            Errors: [
              { NextAction: "disconnect", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "play-error",
          Type: "MessageParticipant",
          Parameters: {
            Text: "Sorry, something went wrong. Goodbye.",
          },
          Transitions: {
            NextAction: "disconnect",
            Errors: [
              { NextAction: "disconnect", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "disconnect",
          Type: "DisconnectParticipant",
          Parameters: {},
          Transitions: {},
        },
    ];

    if (escalationQueueArn) {
      actions.push(
        {
          Identifier: "check-escalation",
          Type: "Compare",
          Parameters: {
            ComparisonValue: "$.Lex.SessionAttributes.conversation_state",
          },
          Transitions: {
            NextAction: "disconnect",
            Conditions: [
              {
                NextAction: "set-escalation-queue",
                Condition: {
                  Operator: "Equals",
                  Operands: ["escalating"],
                },
              },
            ],
            Errors: [
              { NextAction: "disconnect", ErrorType: "NoMatchingCondition" },
            ],
          },
        },
        {
          Identifier: "set-escalation-queue",
          Type: "UpdateContactTargetQueue",
          Parameters: {
            QueueId: escalationQueueArn,
          },
          Transitions: {
            NextAction: "transfer-to-escalation",
            Errors: [
              { NextAction: "disconnect", ErrorType: "NoMatchingError" },
            ],
          },
        },
        {
          Identifier: "transfer-to-escalation",
          Type: "TransferContactToQueue",
          Parameters: {},
          Transitions: {
            NextAction: "disconnect",
            Errors: [
              { NextAction: "disconnect", ErrorType: "QueueAtCapacity" },
              { NextAction: "disconnect", ErrorType: "NoMatchingError" },
            ],
          },
        },
      );
    }

    const flowContent = JSON.stringify({
      Version: "2019-10-30",
      StartAction: "router-invoke",
      Actions: actions,
    });

    this.verificationFlow = new connect.CfnContactFlow(
      this,
      "VerificationFlow",
      {
        instanceArn: this.connectInstance.attrArn,
        name: `${envConfig.resourcePrefix}-verification`,
        type: "CONTACT_FLOW",
        content: flowContent,
      },
    );
    this.verificationFlow.applyRemovalPolicy(removal);

    // -- Outputs --
    new cdk.CfnOutput(this, "ConnectInstanceId", {
      value: this.connectInstance.attrId,
    });
    new cdk.CfnOutput(this, "ConnectInstanceArn", {
      value: this.connectInstance.attrArn,
    });
    new cdk.CfnOutput(this, "VerificationFlowArn", {
      value: this.verificationFlow.attrContactFlowArn,
    });
    new cdk.CfnOutput(this, "RouterLambdaArn", {
      value: this.routerLambda.functionArn,
    });
  }
}
