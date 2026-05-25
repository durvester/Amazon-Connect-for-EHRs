import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { ConnectStack } from "../lib/connect-stack";
import { PhoneRoutingStack } from "../lib/phone-routing-stack";

function buildStack(): cdk.Stack {
  const app = new cdk.App();
  const phoneRouting = new PhoneRoutingStack(app, "pf-voice-qa-phone-routing", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
  return new ConnectStack(app, "pf-voice-qa-connect", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
    phoneRoutingTable: phoneRouting.table,
    lexBotAliasArn:
      "arn:aws:lex:us-east-1:086514900943:bot-alias/TESTBOT/TESTALIAS",
    escalationQueueArn:
      "arn:aws:connect:us-east-1:086514900943:instance/INST/queue/QUEUE",
  });
}

describe("ConnectStack (qa) — ADR-0018 + ADR-0020", () => {
  const t = Template.fromStack(buildStack());

  it("creates exactly one Connect instance with inbound only", () => {
    t.resourceCountIs("AWS::Connect::Instance", 1);
    t.hasResourceProperties("AWS::Connect::Instance", {
      Attributes: Match.objectLike({
        InboundCalls: true,
        OutboundCalls: false,
      }),
      IdentityManagementType: "CONNECT_MANAGED",
    });
  });

  it("creates a router Lambda that reads the phone_routing table", () => {
    t.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "pf-voice-qa-router",
      Runtime: "python3.12",
      Handler: "router_lookup.handler.handler",
    });
  });

  it("contact flow uses InvokeLambdaFunction for the router", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    expect(Object.keys(flows)).toHaveLength(1);
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).toMatch(/InvokeLambdaFunction/);
  });

  it("contact flow uses pf_org_uuid (ADR-0020)", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).toMatch(/pf_org_uuid/);
  });

  it("contact flow hands off to Lex via ConnectParticipantWithLexBot", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).toMatch(/ConnectParticipantWithLexBot/);
    expect(rendered).toMatch(/LexV2Bot/);
    expect(rendered).toMatch(/AliasArn/);
  });

  it("contact flow passes pf_org_uuid, caller_phone, call_id as Lex session attributes", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).toMatch(/LexSessionAttributes/);
    expect(rendered).toMatch(/pf_org_uuid/);
    expect(rendered).toMatch(/caller_phone/);
    expect(rendered).toMatch(/call_id/);
  });

  it("contact flow has escalation routing with Compare + TransferToQueue", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).toMatch(/Compare/);
    expect(rendered).toMatch(/conversation_state/);
    expect(rendered).toMatch(/escalating/);
    expect(rendered).toMatch(/UpdateContactTargetQueue/);
    expect(rendered).toMatch(/TransferContactToQueue/);
  });

  it("does NOT use any non-existent flow actions", () => {
    const flows = t.findResources("AWS::Connect::ContactFlow");
    const flow = Object.values(flows)[0];
    const rendered = JSON.stringify(flow.Properties.Content);
    expect(rendered).not.toMatch(/InvokeAWSService/);
    expect(rendered).not.toMatch(/InvokeAIAgent/);
    expect(rendered).not.toMatch(/GetCustomerInput/);
  });

  it("exposes Connect instance and flow ARN outputs", () => {
    t.hasOutput("ConnectInstanceId", {});
    t.hasOutput("ConnectInstanceArn", {});
    t.hasOutput("VerificationFlowArn", {});
    t.hasOutput("RouterLambdaArn", {});
  });
});
