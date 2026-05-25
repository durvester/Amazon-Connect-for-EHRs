import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Match, Template } from "aws-cdk-lib/assertions";

import { envs } from "../config/envs";
import { AgentGatewayStack } from "../lib/agent-gateway-stack";

function buildStack(): cdk.Stack {
  const app = new cdk.App();
  // The stack provisions the Lambdas it points Gateway at, so the
  // test doesn't need to inject them.
  return new AgentGatewayStack(app, "pf-voice-qa-agent-gateway", {
    env: { account: envs.qa.account, region: envs.qa.region },
    envConfig: envs.qa,
  });
}

describe("AgentGatewayStack (qa)", () => {
  const t = Template.fromStack(buildStack());

  it("creates one AgentCore Gateway", () => {
    t.resourceCountIs("AWS::BedrockAgentCore::Gateway", 1);
  });

  it("creates one Gateway Target for the lookup_patient tool", () => {
    // ADR-0012: one Target per tool. lookup_patient is the only tool
    // landing this session; others arrive in 0010–0012.
    const targets = t.findResources("AWS::BedrockAgentCore::GatewayTarget");
    expect(Object.keys(targets)).toHaveLength(1);
    const target = Object.values(targets)[0];
    const rendered = JSON.stringify(target.Properties);
    expect(rendered).toMatch(/lookup-patient|lookup_patient/);
  });

  it("provisions the lookup_patient Lambda referenced by the Target", () => {
    t.hasResourceProperties("AWS::Lambda::Function", {
      Handler: Match.stringLikeRegexp(".*handler"),
      Runtime: Match.stringLikeRegexp("python3\\.(12|13)"),
      FunctionName: Match.stringLikeRegexp("pf-voice-qa-lookup-patient"),
    });
  });

  it("uses env-suffixed resource names per ADR-0008", () => {
    // The Gateway itself should be named with the resourcePrefix.
    t.hasResourceProperties("AWS::BedrockAgentCore::Gateway", {
      Name: Match.stringLikeRegexp("^pf-voice-qa-"),
    });
  });

  it("exposes the gateway id and URL as stack outputs", () => {
    t.hasOutput("GatewayId", {});
    t.hasOutput("GatewayArn", {});
  });
});
