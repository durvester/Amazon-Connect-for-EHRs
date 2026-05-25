"""Bedrock Agent action group Lambda (ADR-0021).

Receives function calls from the Bedrock Agent, reads session attributes
(pf_org_uuid, caller_phone, call_id) set by the Connect contact flow,
and dispatches to lookup_patient or escalate_to_human.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _params_to_dict(parameters: list[dict]) -> dict[str, str]:
    return {p["name"]: p["value"] for p in parameters if "name" in p and "value" in p}


def _call_lookup_patient(event: dict) -> dict:
    from lookup_patient.handler import handler as lookup_handler
    return lookup_handler(event, None)


def _make_response(
    event: dict,
    body: dict,
    session_attrs: dict,
) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "function": event["function"],
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(body),
                    }
                }
            },
        },
        "sessionAttributes": session_attrs,
        "promptSessionAttributes": event.get("promptSessionAttributes", {}),
    }


def handler(event: dict, context: Any) -> dict:
    function_name = event.get("function", "")
    params = _params_to_dict(event.get("parameters", []))
    session_attrs = event.get("sessionAttributes", {})

    logger.info(
        "action_group invoked: function=%s, pf_org_uuid=%s",
        function_name,
        session_attrs.get("pf_org_uuid", "unknown"),
    )

    if function_name == "lookup_patient":
        lookup_event = {
            "practice_id": session_attrs.get("pf_org_uuid", ""),
            "call_id": session_attrs.get("call_id", ""),
            "caller_phone": session_attrs.get("caller_phone", ""),
            "name_first": params.get("name_first", ""),
            "name_last": params.get("name_last", ""),
            "date_of_birth": params.get("date_of_birth", ""),
        }
        try:
            result = _call_lookup_patient(lookup_event)
        except Exception:
            logger.exception("lookup_patient failed")
            result = {"status": "error", "candidates": [], "probes_tried": []}
        return _make_response(event, result, session_attrs)

    elif function_name == "escalate_to_human":
        reason = params.get("reason", "unknown")
        logger.info("escalate_to_human: reason=%s", reason)
        result = {"status": "escalated", "reason": reason}
        return _make_response(event, result, session_attrs)

    else:
        logger.warning("unknown function: %s", function_name)
        result = {"error": f"Unknown function: {function_name}"}
        return _make_response(event, result, session_attrs)
