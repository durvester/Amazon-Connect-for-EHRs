# web/

Practice-facing dashboard. React + Vite + TypeScript. Hosted on CloudFront + S3 (CDK in `infra/`). Auth via Cognito.

Pages (real implementation in Session 0008):
- `/` — landing / overview
- `/settings/connect` — "Connect Practice Fusion" OAuth flow CTA
- `/calls` — list of recent calls with verification outcomes
- `/calls/:id` — call detail (transcript, audio, timeline)

## Status

Session 0001 ships only an empty React app + smoke test. Real pages arrive in Session 0008.
