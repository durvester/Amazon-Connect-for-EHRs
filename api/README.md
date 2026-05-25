# api/

Practice-facing API that powers the dashboard. FastAPI on Lambda + API Gateway. Cognito JWT for auth.

Endpoints (implemented in Session 0008):
- `GET  /health`
- `GET  /practices/{practice_id}` — current practice config + OAuth connection status
- `POST /practices/{practice_id}/connect` — kick off OAuth flow
- `GET  /practices/{practice_id}/calls` — list recent calls
- `GET  /calls/{call_id}` — call detail with transcript + audio URL (presigned S3)

All endpoints enforce `practice_id` scoping against the caller's Cognito claims.
