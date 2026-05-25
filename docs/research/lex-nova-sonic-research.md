# Lex + Nova Sonic + Connect: Primary-Source Research

**Date:** 2026-05-24 (Session 0011)
**Purpose:** Verify every CFN/API surface before writing ADRs or CDK code.
Per `feedback_research_before_commitment.md`, no IaC until this doc exists.

---

## 1. Nova Sonic on Lex V2 — CFN Path (VERIFIED)

Nova Sonic speech-to-speech is configured at the **BotLocale** level, not
at the bot or alias level.

**CFN property path:**

```
AWS::Lex::Bot
  └─ BotLocales[]
       └─ UnifiedSpeechSettings
            └─ SpeechFoundationModel
                 ├─ ModelArn (required, String)
                 └─ VoiceId (optional, String)
```

- `ModelArn`: Bedrock foundation model ARN. **Use Nova 2 Sonic:**
  `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-sonic-v1:0`
  Nova Sonic v1 (`amazon.nova-sonic-v1:0`) is marked **Legacy** with
  EOL **September 14, 2026** — too close to our scale-out timeline.
  Source: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-sonic.html
- `VoiceId`: Nova Sonic compatible voice. Per the Connect admin guide,
  valid voices are: **Matthew** (en-US), **Amy** (en-GB), **Olivia**
  (en-AU), **Lupe** (es-US).

`VoiceSettings` (the Polly path) and `UnifiedSpeechSettings` (the Nova
Sonic path) appear mutually exclusive on a locale — use one or the other.

**Sources:**
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-lex-bot-botlocale.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-lex-bot-unifiedspeechsettings.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-lex-bot-speechfoundationmodel.html
- https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html

**Confidence: VERIFIED from primary-source CFN docs.**

---

## 2. Lex V2 CFN Resources (VERIFIED)

| Resource | Purpose |
|---|---|
| `AWS::Lex::Bot` | Bot definition including inline BotLocales, Intents, Slots |
| `AWS::Lex::BotVersion` | Immutable snapshot of a bot version |
| `AWS::Lex::BotAlias` | Named alias → version; per-locale Lambda code-hook config |

All three are GA with full CFN support.

**Source:** https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-lex-bot.html

---

## 3. Two Paths for LLM-Driven Conversation in Lex

### Path A: Lambda Code-Hook (ADR-0018's current design)

Lex collects slots via intents; a Lambda code hook runs on fulfillment,
calls AgentCore Gateway for FHIR tools, returns the next dialog action.

**Code-hook configuration lives on the BotAlias**, not the Bot:

```yaml
AWS::Lex::BotAlias
  BotAliasLocaleSettings:
    - LocaleId: en_US
      BotAliasLocaleSetting:
        Enabled: true
        CodeHookSpecification:
          LambdaCodeHook:
            CodeHookInterfaceVersion: "1.0"
            LambdaArn: "arn:aws:lambda:..."
```

**Lambda input/output contract:**
- Input includes `invocationSource` (`DialogCodeHook` | `FulfillmentCodeHook`),
  `inputTranscript`, `sessionState` (slots, attributes), `interpretations`.
- Response must include `sessionState.dialogAction.type` (`Delegate` |
  `ElicitSlot` | `ElicitIntent` | `ConfirmIntent` | `Close`) and optional
  `messages[]`.

**Sources:**
- https://docs.aws.amazon.com/lexv2/latest/dg/lambda-input-format.html
- https://docs.aws.amazon.com/lexv2/latest/dg/lambda-response-format.html

### Path B: AMAZON.BedrockAgentIntent (NEW FINDING)

A built-in Lex intent that **delegates the entire conversation to a
Bedrock Agent**. The agent handles multi-turn dialog, tool calling, and
reasoning natively. Once activated, the conversation stays with the
Bedrock Agent until it returns `FINISH`.

**CFN property path:**

```
Intent
  └─ BedrockAgentIntentConfiguration
       └─ BedrockAgentConfiguration
            ├─ AgentId (String)
            └─ AliasId (String)
```

This means: Lex (with Nova Sonic for speech) → Bedrock Agent (for
reasoning + tool use) → Action Groups (Lambda functions for FHIR).

**Implications if we chose Path B:**
- No custom code-hook Lambda managing dialog state
- Bedrock Agent handles the verification prompt + multi-turn reasoning
- Action Groups replace AgentCore Gateway as the tool surface
- The verification prompt (`agent/prompts/verification.md`) would become
  the Bedrock Agent's system prompt
- Our existing `lookup_patient` Lambda could be an Action Group function

**Sources:**
- https://docs.aws.amazon.com/lexv2/latest/dg/built-in-intent-bedrockagent.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-lex-bot-bedrockagentintentconfiguration.html

**Confidence: VERIFIED from primary-source CFN and Lex docs.**

**⚠️ Open questions for Path B (unverified):**
- Does `AMAZON.BedrockAgentIntent` work with Nova Sonic speech-to-speech?
  (Both are locale-level features; compatibility not explicitly documented.)
- Can a Bedrock Agent be provisioned entirely via CFN (`AWS::Bedrock::Agent`)?
- What is the Bedrock Agent's latency profile for tool-calling vs. a
  direct Lambda invocation?
- Does Bedrock Agent support session attributes from Connect (practice_id)?

---

## 4. Connect Contact Flow Actions (VERIFIED)

### InvokeLambdaFunction

```json
{
  "Type": "InvokeLambdaFunction",
  "Parameters": {
    "LambdaFunctionARN": "arn:aws:lambda:...",
    "InvocationTimeLimitSeconds": "8",
    "InvocationType": "SYNCHRONOUS",
    "ResponseValidation": { "ResponseType": "STRING_MAP" }
  },
  "Transitions": {
    "NextAction": "...",
    "Errors": [{ "NextAction": "...", "ErrorType": "NoMatchingError" }]
  }
}
```

- **Max timeout: 8 seconds.** Fine for a DDB GetItem (router Lambda).
- Response lands at `$.External.*` in the flow.

### ConnectParticipantWithLexBot (console name: "Get customer input")

```json
{
  "Type": "ConnectParticipantWithLexBot",
  "Parameters": {
    "Text": "Welcome prompt",
    "LexV2Bot": {
      "AliasArn": "arn:aws:lex:us-east-1:...:bot-alias/BOTID/ALIASID"
    },
    "LexSessionAttributes": { "key": "value" }
  },
  "Transitions": {
    "NextAction": "...",
    "Conditions": [
      { "NextAction": "...", "Condition": { "Operator": "Equals", "Operands": ["IntentName"] } }
    ],
    "Errors": [
      { "NextAction": "...", "ErrorType": "InputTimeLimitExceeded" },
      { "NextAction": "...", "ErrorType": "NoMatchingError" },
      { "NextAction": "...", "ErrorType": "NoMatchingCondition" }
    ]
  }
}
```

**⚠️ Important:** The JSON action type is `ConnectParticipantWithLexBot`,
not `GetCustomerInput`. Previous sessions assumed `GetCustomerInput` as
the type name — it's the console label, not the flow-language type.

### UpdateContactAttributes

Required between the router Lambda and the Lex handoff to propagate
`practice_id` into the contact attributes visible to Lex session.

### Set voice block (UpdateContactTextToSpeechVoice)

**JSON type:** `UpdateContactTextToSpeechVoice`

**This is Polly-only, NOT Nova Sonic.** Parameters:
```json
{
  "TextToSpeechVoice": "Joanna",
  "TextToSpeechEngine": "neural",
  "TextToSpeechStyle": "Conversational"
}
```
Valid engines: `standard`, `neural`, `generative`. Valid styles: `None`,
`Conversational`, `Newscaster`.

**⚠️ The Connect admin guide's mention of "Set voice with Generative
speaking style" for Nova Sonic appears to refer to Polly's generative
engine, NOT to Nova Sonic itself.** When Nova Sonic is configured at the
Lex bot locale level via `UnifiedSpeechSettings`, the speech-to-speech
model handles both ASR and TTS within the Lex conversation. The contact
flow does **not** need a Set voice block for Nova Sonic — it just hands
off to the Lex bot via `ConnectParticipantWithLexBot`.

**Source:** https://docs.aws.amazon.com/connect/latest/APIReference/contact-actions-updatecontacttexttospeechvoice.html

**Sources:**
- https://docs.aws.amazon.com/connect/latest/APIReference/interactions-invokelambdafunction.html
- https://docs.aws.amazon.com/connect/latest/APIReference/participant-actions-connectparticipantwithlexbot.html
- https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html

---

## 5. Summary: What We Can Build via IaC

| Piece | CFN support | Notes |
|---|---|---|
| Lex bot with Nova Sonic | ✅ `UnifiedSpeechSettings` | Locale-level config |
| Lex bot version + alias | ✅ GA | Standard resources |
| Lambda code-hook on alias | ✅ `BotAliasLocaleSettings` | Per-locale |
| Bedrock Agent intent | ✅ `BedrockAgentIntentConfiguration` | Built-in intent type |
| Connect flow with Lambda | ✅ `InvokeLambdaFunction` | 8s max timeout |
| Connect flow with Lex bot | ✅ `ConnectParticipantWithLexBot` | Via alias ARN |
| Set voice block | ⚠️ Action type name unverified | Need to confirm JSON type |
| Connect instance | ✅ `AWS::Connect::Instance` | Already deployed |

---

## 6. Open Items Requiring Further Verification

1. **Exact Nova Sonic model ARN** — confirm from Bedrock console or
   `aws bedrock list-foundation-models` at deploy time.
2. **Set voice block JSON type name** — must verify against the flow
   language actions reference before writing flow JSON.
3. **Path B compatibility** — `AMAZON.BedrockAgentIntent` + Nova Sonic
   `UnifiedSpeechSettings` on the same locale: confirmed or not?
4. **Bedrock Agent CFN** — is `AWS::Bedrock::Agent` GA with action
   group support?
