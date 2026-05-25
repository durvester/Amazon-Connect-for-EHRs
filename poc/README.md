# POC: Bedrock Agent + ElevenLabs Voice Verification

## What This Is

A throwaway POC testing whether a Bedrock Agent (Claude Sonnet 4.6) can autonomously handle patient verification + FHIR records lookup, invoked from Connect via Lex's `AMAZON.BedrockAgentIntent`, with ElevenLabs TTS for natural voice quality.

This is a decoupled alternative to the current code-hook Lambda architecture. If it works, it replaces ~550 lines of custom orchestration code with a managed Bedrock Agent.

## Architecture

```
Caller → Connect flow
           → Set voice: ElevenLabs (TTS)
           → Router Lambda → pf_org_uuid
           → Get Customer Input → Lex bot (standard ASR)
               → AMAZON.BedrockAgentIntent
                   → Bedrock Agent (Claude Sonnet 4.6)
                       → search_patient (Lambda → PF FHIR)
                       → get_patient_records (Lambda → PF FHIR)
```

## Current Status (Session 0014)

### Done

| Chunk | Status | Details |
|---|---|---|
| 1. `search_patient` Lambda | DEPLOYED + TESTED | `pf-voice-poc-search-patient` — found Mohit via phone probe |
| 2. `get_patient_records` Lambda | DEPLOYED + TESTED | `pf-voice-poc-get-patient-records` — returned 5 active conditions |
| 3. IAM Roles | CREATED | `pf-voice-poc-agent-role`, `pf-voice-poc-lambda-role`, `pf-voice-poc-lex-role` |
| 4. Lambda deployment | COMPLETE | Both Lambdas live, tested with direct invoke |
| 5. Bedrock Agent | NOT STARTED | Next chunk |
| 6. Lex Bot + BedrockAgentIntent | NOT STARTED | The compatibility test |
| 7. Connect Flow + ElevenLabs + DID | NOT STARTED | End-to-end voice test |

### Deployed AWS Resources

| Resource | Name/ARN | Type |
|---|---|---|
| Lambda | `pf-voice-poc-search-patient` | Function |
| Lambda | `pf-voice-poc-get-patient-records` | Function |
| IAM Role | `pf-voice-poc-agent-role` | Bedrock Agent execution |
| IAM Role | `pf-voice-poc-lambda-role` | Lambda execution (DDB + KMS + Secrets) |
| IAM Role | `pf-voice-poc-lex-role` | Lex bot (InvokeAgent + InvokeModel) |

### Existing Resources Used (read-only)

| Resource | Name | Purpose |
|---|---|---|
| DDB Table | `pf-voice-qa-practices` | Practice FHIR config (base URL, client ID, secret ARN) |
| DDB Table | `pf-voice-qa-oauth-tokens` | KMS-encrypted access/refresh tokens |
| KMS Key | `8cbe704a-68f2-4b3b-8058-1cdf6dd345b5` | OAuth token envelope encryption |
| Connect Instance | `bc48ce14-1766-44c9-807b-4807e6010dd6` | Telephony |
| Router Lambda | `pf-voice-qa-router` | DID → pf_org_uuid lookup |

### Test Data

| Item | Value |
|---|---|
| Test practice | `pf_org_uuid: b4ab304f-d1ac-4565-8dca-992b589422a7` |
| Test patient | Mohit Durve, `patient_id: b79082d9-548c-454e-9fc7-ce19ab630776` |
| Test phone | `+17163619276` |
| Test DOB | `1991-06-09` |
| Conditions | Nicotine dependence, Essential hypertension, Heart failure, COPD, Hyperlipidemia |

## Files

```
poc/
├── README.md                         ← this file
├── agent-instructions.md             ← Bedrock Agent system prompt (~40 lines)
├── search_patient/
│   └── handler.py                    ← Lambda: patient lookup via PF FHIR (~130 lines)
└── get_patient_records/
    └── handler.py                    ← Lambda: clinical records via PF FHIR (~160 lines)
```

## Next Session Pickup

### Read these first
1. This file (`poc/README.md`)
2. `poc/agent-instructions.md` — the Bedrock Agent prompt
3. `poc/search_patient/handler.py` — search tool (deployed, tested)
4. `poc/get_patient_records/handler.py` — records tool (deployed, tested)

### Chunk 5: Create Bedrock Agent (next step)

```bash
# 5.1: Create the agent
aws bedrock-agent create-agent \
  --agent-name "pf-voice-poc-agent" \
  --foundation-model "us.anthropic.claude-sonnet-4-6" \
  --agent-resource-role-arn "arn:aws:iam::086514900943:role/pf-voice-poc-agent-role" \
  --instruction "$(cat poc/agent-instructions.md)" \
  --idle-session-ttl-in-seconds 600
# Capture agentId from response

# 5.2: Create action group — patient-lookup
aws bedrock-agent create-agent-action-group \
  --agent-id <AGENT_ID> \
  --agent-version DRAFT \
  --action-group-name "patient-lookup" \
  --action-group-executor '{"lambda": "arn:aws:lambda:us-east-1:086514900943:function:pf-voice-poc-search-patient"}' \
  --function-schema '{
    "functions": [{
      "name": "search_patient",
      "description": "Search for patients in this practice by phone number, name, and/or date of birth. On the first turn, call this with just the phone to check if the caller is already on file.",
      "parameters": {
        "phone": {"type": "string", "description": "Phone number to search (E.164 format like +17163619276)", "required": false},
        "first_name": {"type": "string", "description": "Patient first name", "required": false},
        "last_name": {"type": "string", "description": "Patient last name", "required": false},
        "date_of_birth": {"type": "string", "description": "Date of birth in YYYY-MM-DD format", "required": false}
      }
    }]
  }'

# 5.3: Create action group — patient-records
aws bedrock-agent create-agent-action-group \
  --agent-id <AGENT_ID> \
  --agent-version DRAFT \
  --action-group-name "patient-records" \
  --action-group-executor '{"lambda": "arn:aws:lambda:us-east-1:086514900943:function:pf-voice-poc-get-patient-records"}' \
  --function-schema '{
    "functions": [{
      "name": "get_patient_records",
      "description": "Get medical records for a verified patient. Only call this AFTER the patient has been verified. Returns voice-safe summaries (never lab values, dosages, or clinical codes).",
      "parameters": {
        "patient_id": {"type": "string", "description": "The patient FHIR resource ID from search_patient results", "required": true},
        "resource_type": {"type": "string", "description": "One of: Condition, MedicationRequest, DiagnosticReport, Encounter, AllergyIntolerance, Immunization, Observation, Procedure, DocumentReference, CarePlan, CareTeam, Goal", "required": true},
        "filters": {"type": "string", "description": "Optional FHIR search filters like status=active or _count=5 or _sort=-date", "required": false}
      }
    }]
  }'

# 5.4: Grant Lambda permissions to Bedrock Agent
aws lambda add-permission \
  --function-name pf-voice-poc-search-patient \
  --statement-id BedrockAgentInvoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn "arn:aws:bedrock:us-east-1:086514900943:agent/<AGENT_ID>"

aws lambda add-permission \
  --function-name pf-voice-poc-get-patient-records \
  --statement-id BedrockAgentInvoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn "arn:aws:bedrock:us-east-1:086514900943:agent/<AGENT_ID>"

# 5.5: Prepare and alias
aws bedrock-agent prepare-agent --agent-id <AGENT_ID>
# Wait for PREPARED status:
aws bedrock-agent get-agent --agent-id <AGENT_ID> --query "agent.agentStatus"

aws bedrock-agent create-agent-alias \
  --agent-id <AGENT_ID> \
  --agent-alias-name "poc-live"
# Capture agentAliasId

# 5.6: Test (text-only, no voice)
aws bedrock-agent-runtime invoke-agent \
  --agent-id <AGENT_ID> \
  --agent-alias-id <ALIAS_ID> \
  --session-id "test-1" \
  --input-text "Hello" \
  --session-state '{"sessionAttributes":{"pf_org_uuid":"b4ab304f-d1ac-4565-8dca-992b589422a7","caller_phone":"+17163619276","call_id":"test-001"}}'
# Expected: Agent calls search_patient → finds Mohit → "Hi, is this Mohit?"
```

**IMPORTANT:** The agent MUST have User Input ENABLED in Additional Settings, otherwise it can't ask follow-up questions. Check via console or `update-agent`.

### Chunk 6: Create Lex Bot with BedrockAgentIntent

```bash
# Create bot
aws lexv2-models create-bot \
  --bot-name "pf-voice-poc" \
  --role-arn "arn:aws:iam::086514900943:role/pf-voice-poc-lex-role" \
  --data-privacy '{"childDirected": false}' \
  --idle-session-ttl-in-seconds 600
# Capture botId

# Create locale
aws lexv2-models create-bot-locale \
  --bot-id <BOT_ID> --bot-version DRAFT --locale-id en_US \
  --nlu-intent-confidence-threshold 0.4

# Create BedrockAgentIntent
aws lexv2-models create-intent \
  --bot-id <BOT_ID> --bot-version DRAFT --locale-id en_US \
  --intent-name "VerifyAndServe" \
  --parent-intent-signature "AMAZON.BedrockAgentIntent"
# Configure agent ID + alias via console if CLI doesn't expose bedrockAgentIntentConfiguration

# Console steps:
# 1. Open bot → Generative AI → Enable BedrockAgentIntent
# 2. Open intent → set Agent ID + Alias ID
# 3. Build locale

# Build, version, alias
aws lexv2-models build-bot-locale --bot-id <BOT_ID> --bot-version DRAFT --locale-id en_US
aws lexv2-models create-bot-version --bot-id <BOT_ID> --bot-version-locale-specification '{"en_US":{"sourceBotVersion":"DRAFT"}}'
aws lexv2-models create-bot-alias --bot-id <BOT_ID> --bot-alias-name "poc-live" --bot-version <VERSION>
```

### Chunk 7: Connect Flow + ElevenLabs + DID

1. Store ElevenLabs API key in Secrets Manager: `pf-voice-poc-elevenlabs-key`
2. Associate Lex bot with Connect instance
3. Create contact flow in Connect console:
   - Set voice → ElevenLabs (model: `eleven_turbo_v2_5`, voice: `Rachel`)
   - Invoke Lambda → `pf-voice-qa-router`
   - Set contact attributes → `pf_org_uuid`
   - Get customer input → Lex bot `pf-voice-poc` with session attrs: `pf_org_uuid`, `caller_phone`, `call_id`
   - Disconnect
4. Claim new US DID, associate with flow
5. Add phone_routing row: `{phone_number: "+1XXXXXXXXXX", pf_org_uuid: "b4ab304f-...", status: "active"}`

### Chunk 8: Test + Compare

Call the new DID:
- Does ElevenLabs voice sound natural?
- Does verification work (phone probe → name confirmation → DOB)?
- Do FHIR records queries work?
- What's the per-turn latency vs existing system (`+16156250631`)?

## Teardown

All POC resources are prefixed `pf-voice-poc-*`. Delete in reverse order:

```bash
# 1. Phone routing row
aws dynamodb delete-item --table-name pf-voice-qa-phone-routing --key '{"phone_number":{"S":"+1XXXXXXXXXX"}}'

# 2. Release DID
aws connect release-phone-number --phone-number-id <ID>

# 3. Disassociate Lex bot
aws connect disassociate-bot --instance-id bc48ce14-1766-44c9-807b-4807e6010dd6 --lex-v2-bot '{"aliasArn":"arn:aws:lex:us-east-1:086514900943:bot-alias/<BOT_ID>/<ALIAS_ID>"}'

# 4. Delete Lex bot
aws lexv2-models delete-bot-alias --bot-id <BOT_ID> --bot-alias-id <ALIAS_ID>
aws lexv2-models delete-bot --bot-id <BOT_ID> --skip-resource-in-use-check

# 5. Delete Bedrock Agent
aws bedrock-agent delete-agent-alias --agent-id <AGENT_ID> --agent-alias-id <ALIAS_ID>
aws bedrock-agent delete-agent --agent-id <AGENT_ID> --skip-resource-in-use-check

# 6. Delete Lambdas
aws lambda delete-function --function-name pf-voice-poc-search-patient
aws lambda delete-function --function-name pf-voice-poc-get-patient-records

# 7. Delete Secrets Manager secret (if created)
aws secretsmanager delete-secret --secret-id pf-voice-poc-elevenlabs-key --force-delete-without-recovery

# 8. Delete IAM roles
for role in pf-voice-poc-agent-role pf-voice-poc-lambda-role pf-voice-poc-lex-role; do
  for policy in $(aws iam list-role-policies --role-name $role --query "PolicyNames" --output text 2>/dev/null); do
    aws iam delete-role-policy --role-name $role --policy-name $policy
  done
  for arn in $(aws iam list-attached-role-policies --role-name $role --query "AttachedPolicies[].PolicyArn" --output text 2>/dev/null); do
    aws iam detach-role-policy --role-name $role --policy-arn $arn
  done
  aws iam delete-role --role-name $role
done
```

## Why This Architecture

The current system (Session 0013) uses a code-hook Lambda that calls Claude directly via `InvokeModel` every turn, manages conversation history in Lex session attributes (12KB limit), and dispatches tools via `if/elif`. It works but:

1. **Session attribute limit** — 12KB forces conversation truncation on longer calls
2. **Tightly coupled** — agent logic is welded to Lex's code-hook contract, can't serve web chat
3. **Manual orchestration** — ~550 lines of history management, tool dispatch, phase tracking
4. **No managed guardrails** — safety is prompt-only

The Bedrock Agent architecture gives:
- Managed conversation memory (no 12KB limit)
- Tool dispatch via action groups (no custom code)
- Multi-channel ready (same agent serves Lex voice, API chat, SMS)
- Bedrock Guardrails support (PII filtering, denied topics)
- ~40 lines of prompt + ~290 lines of Lambda (vs ~550 + ~230 lines today)

## Key Decisions Made

- **ElevenLabs TTS instead of Nova Sonic** — sidesteps the undocumented Nova Sonic + BedrockAgentIntent compatibility question. ElevenLabs is natively supported in Connect via the `Set voice` block.
- **Fresh Lambdas, not wrappers** — each Lambda is self-contained (~130-160 lines) with inline FHIR auth. No shared modules, no dependency on the existing codebase.
- **Same Connect instance** — the isolation boundary is the Lex bot + contact flow + DID, not the Connect instance. Zero risk to existing system.
- **Two tools, not four** — `search_patient` and `get_patient_records`. `complete_verification` is unnecessary (the agent tracks verification state in its own memory). `escalate_to_human` is unnecessary for POC (agent just says goodbye).
