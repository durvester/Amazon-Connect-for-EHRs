# infra/

AWS CDK app (TypeScript) for the Practice Fusion voice verification platform.

## Stacks (filled in across Sessions 0007–0010)

| Stack | Purpose | First written in |
|---|---|---|
| `DataStack` | DynamoDB tables, S3 buckets, KMS CMKs | Session 0007 |
| `ApiStack` | API Gateway + OAuth Lambda + Practice API Lambda + Cognito | Session 0007 |
| `AgentStack` | AgentCore Runtime config, tool Lambdas | Session 0007 |
| `ConnectStack` | Amazon Connect instance, DID, contact flow | Session 0010 |

## Commands

```bash
npm install
npm run build      # tsc
npm run synth      # cdk synth --quiet
npm test           # jest snapshot tests
npm run deploy     # cdk deploy --all   (Sessions 0007+, requires SSO login)
```

## Status

Session 0001 ships only the scaffold + an empty `App` so `cdk synth` succeeds. Real stacks arrive in Session 0007.
