"""LLM-powered Lex V2 code-hook Lambda (ADR-0019).

Every caller utterance arrives via FallbackIntent fulfillmentCodeHook.
The handler calls Bedrock InvokeModel (Claude) with the patient service
prompt + conversation history, executes any tool calls Claude requests
(lookup_patient, complete_verification, fhir_query, escalate_to_human),
and returns ElicitIntent (continue) or Close (done).

Session 0013: two-phase conversation — verification then service.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_TURNS = 10
_MAX_TOOL_ROUNDS = 5
_MAX_HISTORY_BYTES = 8000
_DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

_bedrock = None
_system_prompt_text: str | None = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def _load_system_prompt() -> str:
    global _system_prompt_text
    if _system_prompt_text is None:
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "patient_service.md")
        if not os.path.exists(prompt_path):
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "verification.md")
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                _system_prompt_text = f.read()
        else:
            _system_prompt_text = os.environ.get("VERIFICATION_PROMPT", "")
            if not _system_prompt_text:
                _system_prompt_text = (
                    "You are answering the phone for a medical practice. "
                    "Your job is to verify the caller's identity by collecting "
                    "their first name, last name, and date of birth, then calling "
                    "the lookup_patient tool. Follow HIPAA privacy rules strictly."
                )
    return _system_prompt_text


_TOOL_DEFINITIONS = [
    {
        "name": "lookup_patient",
        "description": (
            "Search the practice's FHIR endpoint for Patient resources matching "
            "caller-provided identity inputs. Returns a candidate list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "practice_id": {"type": "string", "description": "The pf_org_uuid for this practice"},
                "call_id": {"type": "string", "description": "Connect contact id"},
                "caller_phone": {"type": "string", "description": "Caller ANI in E.164"},
                "name_first": {"type": "string", "description": "Caller-provided first name"},
                "name_last": {"type": "string", "description": "Caller-provided last name"},
                "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["practice_id", "call_id", "caller_phone"],
        },
    },
    {
        "name": "complete_verification",
        "description": (
            "Mark the caller as verified. Call this after confirming the caller's "
            "identity with exactly one patient match. Sets the conversation to "
            "service phase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "The verified patient's FHIR id"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "fhir_query",
        "description": (
            "Query the practice's FHIR endpoint for clinical resources (labs, "
            "medications, encounters, documents, observations) for the verified "
            "patient. Only available after verification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "practice_id": {"type": "string", "description": "The pf_org_uuid"},
                "call_id": {"type": "string", "description": "Connect contact id"},
                "patient_id": {"type": "string", "description": "Verified patient FHIR id"},
                "resource_type": {
                    "type": "string",
                    "description": "DiagnosticReport, MedicationRequest, Encounter, DocumentReference, or Observation",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional search filters: status, category, date, _count, _sort",
                },
            },
            "required": ["practice_id", "call_id", "patient_id", "resource_type"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Transfer the caller to a human agent with a reason code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "One of: rate_limited, credentials_expired, lookup_error, no_match, ambiguous, phone_mismatch, caller_request",
                },
            },
            "required": ["reason"],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, session_attrs: dict | None = None) -> dict:
    if tool_name == "lookup_patient":
        from lookup_patient.handler import handler as lookup_handler
        return lookup_handler(tool_input, None)
    elif tool_name == "complete_verification":
        patient_id = tool_input.get("patient_id", "")
        if session_attrs is not None:
            session_attrs["verified_patient_id"] = patient_id
            session_attrs["conversation_phase"] = "service"
        return {"status": "verified", "patient_id": patient_id}
    elif tool_name == "fhir_query":
        if session_attrs is None or session_attrs.get("conversation_phase") != "service":
            return {"status": "error", "error": "Verification required before querying records", "results": []}
        from fhir_query.handler import handler as fhir_handler
        return fhir_handler(tool_input, None)
    elif tool_name == "escalate_to_human":
        logger.info("escalate_to_human: reason=%s", tool_input.get("reason"))
        return {"status": "escalated", "reason": tool_input.get("reason", "unknown")}
    else:
        logger.warning("unknown tool requested: %s", tool_name)
        return {"error": f"Unknown tool: {tool_name}"}


def _should_close(claude_response: dict, session_attrs: dict) -> bool:
    if session_attrs.get("conversation_state") == "escalating":
        return True
    content = claude_response.get("content", [])
    for block in content:
        if block.get("type") == "tool_use" and block.get("name") == "escalate_to_human":
            return True
    return False


def _proactive_phone_probe(session_attrs: dict) -> dict | None:
    """Run a phone-only Patient search on the first turn to identify the caller."""
    caller_phone = session_attrs.get("caller_phone", "")
    practice_id = session_attrs.get("pf_org_uuid", "")
    if not caller_phone or not practice_id:
        return None

    try:
        from oauth.credentials import CredentialsExpired, get_credentials
        from lookup_patient.fhir_client import FhirClientError, read_patient, search_patient_by_phone

        base_url, access_token, refresh_ctx = get_credentials(practice_id)
        raw = search_patient_by_phone(
            caller_phone, base_url, access_token,
            refresh_access_token=refresh_ctx,
        )

        if raw["match"] == "single":
            enrichment = read_patient(
                raw["patient_id"], base_url, access_token,
                refresh_access_token=refresh_ctx,
            )
            return {
                "match": "single",
                "patient_id": raw["patient_id"],
                "name_first": enrichment.get("name_first", ""),
                "name_last": enrichment.get("name_last", ""),
                "date_of_birth": enrichment.get("date_of_birth", ""),
                "phone_masked": enrichment.get("phone_masked", ""),
            }
        elif raw["match"] == "multiple":
            candidates = []
            for pid in raw["candidates"][:5]:
                enrichment = read_patient(
                    pid, base_url, access_token,
                    refresh_access_token=refresh_ctx,
                )
                candidates.append({"patient_id": pid, **enrichment})
            return {"match": "multiple", "candidates": candidates}
        else:
            return {"match": "none"}
    except Exception:
        logger.exception("proactive phone probe failed — falling back to standard flow")
        return None


def _is_goodbye(text: str, session_attrs: dict) -> bool:
    if session_attrs.get("conversation_phase") != "service":
        return False
    lower = text.lower()
    return any(word in lower for word in ("goodbye", "good bye", "bye", "thank you for calling"))


def _truncate_history(messages: list[dict]) -> str:
    """Serialize messages to JSON, trimming oldest turns if over budget.

    Never breaks a tool_use/tool_result pair — finds safe cut points
    where the message is a user text message (not a tool_result).
    """
    history_json = json.dumps(messages)
    if len(history_json) <= _MAX_HISTORY_BYTES:
        return history_json

    trimmed = list(messages)
    while len(json.dumps(trimmed)) > _MAX_HISTORY_BYTES and len(trimmed) > 2:
        cut = _find_safe_cut(trimmed)
        trimmed = trimmed[cut:]

    return json.dumps(trimmed)


def _find_safe_cut(messages: list[dict]) -> int:
    """Find the earliest index where we can safely trim without orphaning
    a tool_use/tool_result pair. Returns how many messages to remove."""
    for i in range(2, len(messages)):
        msg = messages[i]
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list) and content and content[0].get("type") == "tool_result":
                continue
            return i
    return 2


def _sanitize_history(messages: list[dict]) -> list[dict]:
    """Remove orphaned tool_use blocks that lack a following tool_result."""
    clean: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in (content if isinstance(content, list) else [])
            )
            if has_tool_use:
                if i + 1 < len(messages):
                    next_msg = messages[i + 1]
                    next_content = next_msg.get("content", [])
                    has_tool_result = (
                        next_msg.get("role") == "user"
                        and isinstance(next_content, list)
                        and next_content
                        and next_content[0].get("type") == "tool_result"
                    )
                    if has_tool_result:
                        clean.append(msg)
                        clean.append(next_msg)
                        i += 2
                        continue
                i += 1
                continue
        clean.append(msg)
        i += 1
    return clean


def _build_messages(conversation_history: list[dict], current_transcript: str) -> list[dict]:
    messages = list(conversation_history)
    text = current_transcript.strip() if current_transcript else ""
    if not text:
        text = "[caller just connected]"
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": text}],
    })
    return messages


def _call_claude(messages: list[dict], system_prompt: str) -> dict:
    model_id = os.environ.get("BEDROCK_MODEL_ID", _DEFAULT_MODEL_ID)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": [{"type": "text", "text": system_prompt}],
        "messages": messages,
        "tools": _TOOL_DEFINITIONS,
    }
    response = _get_bedrock().invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    return json.loads(response["body"].read())


def _extract_text(claude_response: dict) -> str:
    for block in claude_response.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


def _extract_tool_use(claude_response: dict) -> dict | None:
    for block in claude_response.get("content", []):
        if block.get("type") == "tool_use":
            return block
    return None


def _elicit_intent(session_attrs: dict, message: str) -> dict:
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitIntent"},
            "sessionAttributes": session_attrs,
        },
        "messages": [
            {"contentType": "PlainText", "content": message},
        ],
    }


def _close(session_attrs: dict, state: str, message: str) -> dict:
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": "FallbackIntent", "state": state},
            "sessionAttributes": session_attrs,
        },
        "messages": [
            {"contentType": "PlainText", "content": message},
        ],
    }


def handler(event: dict, context: object) -> dict:
    invocation_source = event.get("invocationSource", "")
    input_transcript = event.get("inputTranscript", "")
    session_state = event.get("sessionState", {})
    session_attrs = dict(session_state.get("sessionAttributes", {}))

    logger.info(
        "code-hook invoked: source=%s, transcript_len=%d, pf_org_uuid=%s, phase=%s",
        invocation_source,
        len(input_transcript),
        session_attrs.get("pf_org_uuid", "unknown"),
        session_attrs.get("conversation_phase", "verification"),
    )

    conversation_history: list[dict] = []
    raw_history = session_attrs.get("conversation_history", "")
    if raw_history:
        try:
            conversation_history = _sanitize_history(json.loads(raw_history))
        except json.JSONDecodeError:
            logger.warning("failed to parse conversation_history, starting fresh")

    if len(conversation_history) >= MAX_TURNS * 2:
        return _close(
            session_attrs,
            "Failed",
            "I'm sorry, let me transfer you to someone who can help.",
        )

    is_first_turn = (
        not conversation_history
        and session_attrs.get("conversation_phase", "verification") == "verification"
    )
    if is_first_turn and not session_attrs.get("phone_probe_result"):
        phone_probe = _proactive_phone_probe(session_attrs)
        if phone_probe:
            session_attrs["phone_probe_result"] = json.dumps(phone_probe)
            logger.info(
                "phone probe: match=%s",
                phone_probe.get("match", "error"),
            )

    base_prompt = _load_system_prompt()
    phone_probe_ctx = ""
    raw_probe = session_attrs.get("phone_probe_result", "")
    if raw_probe:
        phone_probe_ctx = f"- phone_probe_result: {raw_probe}\n"

    context_block = (
        "\n\n## Session Context (injected by system — not caller-provided)\n"
        f"- pf_org_uuid: {session_attrs.get('pf_org_uuid', 'UNKNOWN')}\n"
        f"- call_id: {session_attrs.get('call_id', 'UNKNOWN')}\n"
        f"- caller_phone: {session_attrs.get('caller_phone', 'UNKNOWN')}\n"
        f"- conversation_phase: {session_attrs.get('conversation_phase', 'verification')}\n"
        f"- verified_patient_id: {session_attrs.get('verified_patient_id', 'NONE')}\n"
        f"{phone_probe_ctx}"
    )
    system_prompt = base_prompt + context_block
    messages = _build_messages(conversation_history, input_transcript)

    escalating = False
    final_text = ""
    claude_response: dict = {}

    for _round in range(_MAX_TOOL_ROUNDS + 1):
        claude_response = _call_claude(messages, system_prompt)

        if "content" not in claude_response:
            logger.error("bedrock response missing 'content' key: %s", claude_response)
            final_text = "I'm sorry, something went wrong. Let me transfer you."
            escalating = True
            break

        tool_use = _extract_tool_use(claude_response)
        if tool_use is None:
            final_text = _extract_text(claude_response)
            break

        tool_name = tool_use["name"]
        tool_input = tool_use["input"]

        if tool_name == "escalate_to_human":
            escalating = True
            session_attrs["conversation_state"] = "escalating"

        tool_result = _execute_tool(tool_name, tool_input, session_attrs)

        messages.append({"role": "assistant", "content": claude_response["content"]})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": json.dumps(tool_result),
                }
            ],
        })

        if _round == _MAX_TOOL_ROUNDS:
            final_text = _extract_text(claude_response) or "Let me transfer you to someone who can help."
            break

    if not final_text:
        final_text = "Let me transfer you to someone who can help."

    if final_text and (not messages or messages[-1].get("role") != "assistant"):
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": final_text}],
        })

    session_attrs["conversation_history"] = _truncate_history(messages)

    should_close = escalating or _should_close(claude_response, session_attrs)

    if should_close:
        return _close(session_attrs, "Failed", final_text)

    if _is_goodbye(final_text, session_attrs):
        return _close(session_attrs, "Fulfilled", final_text)

    return _elicit_intent(session_attrs, final_text)
