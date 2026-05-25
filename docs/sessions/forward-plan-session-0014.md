# Session 0014 Forward Plan: Practice Onboarding + Dashboard

## Practice JTBDs (Jobs to Be Done)

Working back from what a practice needs, not forward from AWS capabilities.

### Onboarding JTBDs

| # | Job | Metric | Priority |
|---|---|---|---|
| J1 | "I want to connect my practice to this system in under 5 minutes without calling anyone" | Time from landing page to first test call | P0 |
| J2 | "I want to know exactly what data you'll access and what you'll do with it before I authorize" | Consent clarity score (can they explain it back?) | P0 |
| J3 | "I want a phone number that my patients can call, or I want to forward my existing number" | DID provisioned or forwarding instructions provided | P0 |
| J4 | "I want to test the system myself before routing real patients to it" | Test call available before go-live | P1 |
| J5 | "I want to port my existing practice number so patients don't need to learn a new one" | Number porting initiated in onboarding | P2 |

### Operational JTBDs

| # | Job | Metric | Priority |
|---|---|---|---|
| J6 | "I want to see all calls — who called, when, what happened, how long" | Call log with filtering | P0 |
| J7 | "I want to read the transcript of any call" | Transcript viewer | P0 |
| J8 | "I want to know if a call went wrong and why" | Escalation reports, error flags | P1 |
| J9 | "I want to see what patient data was accessed and by whom" | Audit log viewer (HIPAA compliance) | P1 |
| J10 | "I want to intervene if a call is going badly" | Live call monitoring / barge-in | P2 |
| J11 | "I want to customize what the agent says and can do" | Prompt/behavior configuration | P2 |
| J12 | "I want to route calls differently based on time of day or department" | Routing rules editor | P2 |

### Trust JTBDs

| # | Job | Metric | Priority |
|---|---|---|---|
| J13 | "I want to disconnect this system instantly if something goes wrong" | Kill switch (< 1 click) | P0 |
| J14 | "I want to know this is HIPAA compliant without reading a 50-page doc" | Clear, short compliance statement | P0 |
| J15 | "I want to re-authorize if my EHR credentials change" | Reconnect flow | P1 |

---

## Onboarding Flow Design (J1, J2, J3, J4)

### Single-page flow — no accounts, no passwords, no forms

**Step 1: Enter your Practice Fusion URL** (10 seconds)
- Single input field: "Paste your Practice Fusion FHIR URL"
- Helper text: "Find this in Settings → API → FHIR Base URL"
- Auto-detect: validate it's a PF endpoint via `/.well-known/smart-configuration`
- If valid → show practice name from PF → "Is this [Practice Name]?"

**Step 2: Authorize access** (30 seconds)
- Clear permission summary: "We'll access: Patient names, phones, DOBs,
  lab statuses, medication names, visit dates, condition names. We will
  NOT access: lab values, dosages, clinical notes, billing."
- "Authorize with Practice Fusion" button → SMART on FHIR PKCE flow
- Redirect back with tokens → stored encrypted

**Step 3: Get your phone number** (instant)
- "Your patients can reach the AI agent at: (615) 555-XXXX"
- Copy button, SMS-to-self button
- "Or forward your existing number to this number" + forwarding instructions
- Future: "Port my existing number" flow

**Step 4: Make a test call** (60 seconds)
- "Call your new number now to test it"
- Real-time call status indicator on the page
- After test call: "How did it go?" feedback capture

**Step 5: Go live** (instant)
- Toggle: "Accept patient calls" (off by default)
- Summary: phone number, practice name, connection status

### What happens behind the scenes

1. SMART discovery → token endpoint, authorize endpoint
2. PKCE authorization → access_token + refresh_token
3. Write `practices` table (fhir_base_url, token_endpoint, client_id, secret_arn)
4. Write `oauth-tokens` table (encrypted access + refresh)
5. Claim a Connect DID → write `phone_routing` table
6. Return DID to the UI

The existing OAuth onboarding API (`api/src/api/routes.py`) already handles
steps 1-4. It needs: DID claiming (step 5), the web UI (steps 1-5 visually),
and the dashboard (post-onboarding).

---

## Dashboard Design (J6-J12)

### Call Log (J6)
- Table: timestamp, caller phone (masked), patient name (if verified), duration, outcome (verified, escalated, abandoned, error), turns
- Filters: date range, outcome, caller phone
- Click row → transcript + detail view

### Transcript Viewer (J7)
- Turn-by-turn display: caller said / agent said / tool called / result
- Color coding: green = verified, yellow = escalated, red = error
- Timestamp per turn, total duration

### Escalation Reports (J8)
- Grouped by reason: no_match, credentials_expired, caller_request, etc.
- Trend chart: escalation rate over time
- Drill down to specific calls

### Audit Log (J9)
- Which patient data was accessed, when, by which call
- FHIR resource types queried, result counts
- Exportable for HIPAA compliance audits

### Kill Switch (J13)
- Big red "Pause All Calls" button
- Calls route to voicemail or "our phone system is temporarily unavailable"
- Reactivate with one click

### Reconnect (J15)
- OAuth status indicator (green = active, red = expired)
- "Reconnect" button → re-runs SMART flow

---

## Prompt Hardening (before real patients)

1. **Emergency detection:** First line of prompt: "If the caller mentions
   an emergency, chest pain, difficulty breathing, or says they need
   immediate help, say: 'If this is a medical emergency, please hang up
   and dial 911 immediately.' Do this BEFORE any other interaction."

2. **After-hours handling:** Practice config includes business hours.
   Outside hours: "Our office is currently closed. If this is an emergency,
   dial 911. Our office hours are [hours]. Goodbye."

3. **Minors/guardians:** If caller is calling about a child, verification
   should confirm they're the guardian on file.

4. **Non-English callers:** Detect non-English and escalate: "I'm only
   able to help in English right now. Let me connect you with a staff
   member."

---

## Tech Stack for Dashboard + Onboarding UI

**Already in the repo:**
- `web/` — React + Vite + TypeScript (scaffold exists)
- `api/` — FastAPI on Lambda + Function URL (OAuth routes exist)
- `infra/lib/api-stack.ts` — API deployment
- Cognito for auth (in architecture doc, not yet implemented)

**Needs building:**
- React pages: onboarding wizard, dashboard, call log, transcript viewer
- API routes: call history, audit logs, practice config, kill switch
- Connect + CloudWatch data aggregation for call metrics
- Real-time call status (Connect streaming or polling)

---

## Implementation Order for Session 0014

1. CDK deploy (reconcile Session 0013 changes)
2. Prompt hardening (emergency, after-hours)
3. Onboarding UI (React wizard, 5 steps above)
4. Dashboard: call log + transcript viewer
5. Dashboard: audit log + kill switch
6. Live test: full onboarding flow with a second practice

---

## Architecture Decisions Needed

- **ADR-0021:** Real-time call monitoring — Connect Contact Lens vs CloudWatch vs custom streaming
- **ADR-0022:** Dashboard auth — Cognito user pools vs Cognito + Google Workspace SSO
- **ADR-0023:** Number porting — Connect number management API vs manual process
- **ADR-0024:** Call recording storage — S3 lifecycle, retention policy, access controls
