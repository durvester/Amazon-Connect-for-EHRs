"""Tests for Bedrock Agent action group Lambda.

The action group Lambda receives function calls from the Bedrock Agent,
reads session attributes (pf_org_uuid, caller_phone, call_id) from the
event, dispatches to lookup_patient or escalate_to_human, and returns
the result in Bedrock Agent response format.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _make_agent_event(
    *,
    function: str = "lookup_patient",
    parameters: list[dict] | None = None,
    session_attributes: dict | None = None,
) -> dict:
    return {
        "messageVersion": "1.0",
        "agent": {
            "name": "pf-voice-qa-verification",
            "id": "TESTagent",
            "alias": "TESTALIAS",
            "version": "1",
        },
        "inputText": "My name is Mohit Durve and my date of birth is June 9th 1991",
        "sessionId": "session-123",
        "actionGroup": "verification-tools",
        "function": function,
        "parameters": parameters or [],
        "sessionAttributes": session_attributes or {},
        "promptSessionAttributes": {},
    }


class TestLookupPatientDispatch:

    @patch("agent_action_group.handler._call_lookup_patient")
    def test_dispatches_to_lookup_patient_with_session_attrs(self, mock_lookup):
        from agent_action_group.handler import handler

        mock_lookup.return_value = {
            "status": "candidates",
            "candidates": [
                {"patient_id": "p1", "name_first": "Mohit", "name_last": "Durve",
                 "date_of_birth": "1991-06-09", "phone_masked": "9276"}
            ],
            "probes_tried": ["Patient?telecom=+17163619276"],
        }

        event = _make_agent_event(
            function="lookup_patient",
            parameters=[
                {"name": "name_first", "type": "string", "value": "Mohit"},
                {"name": "name_last", "type": "string", "value": "Durve"},
                {"name": "date_of_birth", "type": "string", "value": "1991-06-09"},
            ],
            session_attributes={
                "pf_org_uuid": "b4ab304f-d1ac-4565-8dca-992b589422a7",
                "caller_phone": "+17163619276",
                "call_id": "contact-abc",
            },
        )
        result = handler(event, {})

        mock_lookup.assert_called_once()
        call_args = mock_lookup.call_args[0][0]
        assert call_args["practice_id"] == "b4ab304f-d1ac-4565-8dca-992b589422a7"
        assert call_args["caller_phone"] == "+17163619276"
        assert call_args["call_id"] == "contact-abc"
        assert call_args["name_first"] == "Mohit"
        assert call_args["date_of_birth"] == "1991-06-09"

    @patch("agent_action_group.handler._call_lookup_patient")
    def test_returns_bedrock_agent_response_format(self, mock_lookup):
        from agent_action_group.handler import handler

        mock_lookup.return_value = {"status": "candidates", "candidates": [], "probes_tried": []}

        event = _make_agent_event(
            function="lookup_patient",
            parameters=[],
            session_attributes={"pf_org_uuid": "x", "caller_phone": "+1", "call_id": "c"},
        )
        result = handler(event, {})

        assert result["messageVersion"] == "1.0"
        assert result["response"]["actionGroup"] == "verification-tools"
        assert result["response"]["function"] == "lookup_patient"
        assert "responseBody" in result["response"]["functionResponse"]
        body = json.loads(result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["status"] == "candidates"

    @patch("agent_action_group.handler._call_lookup_patient")
    def test_preserves_session_attributes_in_response(self, mock_lookup):
        from agent_action_group.handler import handler

        mock_lookup.return_value = {"status": "candidates", "candidates": [], "probes_tried": []}

        attrs = {"pf_org_uuid": "x", "caller_phone": "+1", "call_id": "c"}
        event = _make_agent_event(function="lookup_patient", session_attributes=attrs)
        result = handler(event, {})

        assert result["sessionAttributes"] == attrs


class TestEscalateDispatch:

    def test_escalate_returns_reason(self):
        from agent_action_group.handler import handler

        event = _make_agent_event(
            function="escalate_to_human",
            parameters=[{"name": "reason", "type": "string", "value": "no_match"}],
            session_attributes={"pf_org_uuid": "x"},
        )
        result = handler(event, {})

        body = json.loads(result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert body["status"] == "escalated"
        assert body["reason"] == "no_match"


class TestUnknownFunction:

    def test_unknown_function_returns_error(self):
        from agent_action_group.handler import handler

        event = _make_agent_event(function="nonexistent_tool")
        result = handler(event, {})

        body = json.loads(result["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])
        assert "error" in body
