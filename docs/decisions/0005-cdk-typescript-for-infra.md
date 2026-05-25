# ADR-0005: AWS CDK (TypeScript) for all infrastructure as code

**Status:** Accepted
**Date:** 2026-05-23

## Context

The system needs IaC for: Amazon Connect, AgentCore Runtime, Lambdas (Python), DynamoDB, S3, KMS, Cognito, API Gateway, CloudFront. Options:

- **AWS CDK (TypeScript or Python)**
- **Terraform / CDKTF**
- **AWS SAM**
- **AWS CloudFormation directly**

## Decision

**AWS CDK in TypeScript.**

## Why

- **First-class L2 constructs for AWS services we use.** Connect, AgentCore, Cognito, and API Gateway all have CDK constructs that are more ergonomic than equivalent Terraform resources today.
- **TypeScript over Python (for CDK specifically).** Two reasons:
  1. The web dashboard is TypeScript already; reusing the language for infra means contributors switch contexts less often.
  2. Keeping CDK and the Python application code in different languages prevents accidental cross-leakage between runtime and infra (e.g., importing a Lambda handler in a CDK stack).
- **No state-file management.** CloudFormation owns the state; we don't operate Terraform state buckets.

## Consequences

**Positive:**
- Stack snapshot tests are first-class (`@aws-cdk/assertions`).
- L2 constructs encode AWS best practices (least-privilege roles, encryption defaults).
- One IaC language for the whole stack.

**Negative:**
- Cross-account / cross-region resources (later, when we go multi-region) need CDK Pipelines or external orchestration.
- Some newer services lag in CDK L2 support; we may need to drop to L1 (raw CloudFormation) for AgentCore until the L2 catches up.

## Alternatives considered

- **CDK Python.** Equally good; rejected only to keep IaC clearly separated from app code.
- **Terraform.** Better multi-cloud story, but we are AWS-only and Connect/AgentCore lag in Terraform provider support.
- **SAM.** Excellent for serverless but doesn't model Connect, Cognito, or non-serverless services well.
