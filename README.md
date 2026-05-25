# Practice Fusion Voice Verification

AWS-native voice agent that verifies patient identity over the phone for Practice Fusion practices. **Amazon Connect** handles telephony; **Bedrock AgentCore** runs the voice agent (powered by **Amazon Nova Sonic** for speech-to-speech); **Lambda tools** call Practice Fusion's per-practice FHIR endpoint to match the caller against EHR records. A small **React dashboard** lets practice staff review call outcomes and connect their Practice Fusion account via SMART-on-FHIR OAuth.

This repo is in early bootstrap. Read [`docs/context.md`](docs/context.md) and [`docs/architecture.md`](docs/architecture.md) for the full picture. The session log under [`docs/sessions/`](docs/sessions/) is the source of truth for "what's been done and what's next."

## Quickstart

Prerequisites:
- Python 3.12
- Node 22
- AWS CLI v2 (SSO-authenticated to account `086514900943`, region `us-east-1`)
- AWS CDK v2 (`npm i -g aws-cdk`)

```bash
make bootstrap   # install Python + Node dependencies in every workspace
make test        # run all tests (pytest + vitest + cdk synth snapshot tests)
make lint        # ruff + eslint + tsc --noEmit
```

## Layout

| Path | Purpose |
|---|---|
| [`docs/`](docs/) | Context, architecture, ADRs, per-session handoff log |
| [`infra/`](infra/) | AWS CDK app (TypeScript) — Connect, AgentCore, Lambda, DynamoDB, S3, KMS |
| [`agent/`](agent/) | Bedrock AgentCore voice agent (Python, Strands SDK) |
| [`tools/`](tools/) | Lambda tools the agent calls — one directory per tool |
| [`oauth/`](oauth/) | SMART-on-FHIR OAuth onboarding service (FastAPI on Lambda) |
| [`api/`](api/) | Practice-facing API for the dashboard |
| [`web/`](web/) | Practice dashboard (React + Vite + TypeScript) |
| [`scripts/`](scripts/) | One-off spikes and tooling |

## Where to start as a contributor

1. Read [`CLAUDE.md`](CLAUDE.md) (instructions for AI agents) — it summarizes the conventions.
2. Read the **latest** file under [`docs/sessions/`](docs/sessions/) — start from its "Next session pickup" block.
3. Read [`docs/context.md`](docs/context.md) and [`docs/architecture.md`](docs/architecture.md).

## Status

Pre-pilot. No production deployment yet. Pilot target: one practice, Phase 1 (verification-only).
