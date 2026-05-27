"""Tests for the LLM-powered Lex V2 code-hook Lambda (ADR-0019).

The code-hook receives every caller utterance via FallbackIntent
fulfillmentCodeHook. It calls Bedrock InvokeModel (Claude) with the
verification prompt + conversation history, executes any tool calls
Claude requests, and returns ElicitIntent (continue) or Close (done).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _make_lex_event(
    *,
    invocation_source: str = "FulfillmentCodeHook",
    intent_name: str = "FallbackIntent",
    input_transcript: str = "hello",
    session_attributes: dict | None = None,
) -> dict:
    return {
        "messageVersion": "1.0",
        "invocationSource": invocation_source,
        "inputMode": "Speech",
        "responseContentType": "text/plain; charset=utf-8",
        "sessionId": "session-123",
        "inputTranscript": input_transcript,
        "bot": {
            "id": "TESTBOT",
            "name": "pf-voice-qa-verification",
            "localeId": "en_US",
            "version": "1",
            "aliasId": "TESTALIAS",
            "aliasName": "pf-voice-qa-live",
        },
        "interpretations": [
            {
                "intent": {
                    "name": intent_name,
                    "slots": {},
                    "state": "InProgress",
                    "confirmationState": "None",
                },
                "nluConfidence": 0.0,
            }
        ],
        "sessionState": {
            "intent": {
                "name": intent_name,
                "slots": {},
                "state": "InProgress",
                "confirmationState": "None",
            },
            "sessionAttributes": session_attributes or {},
        },
    }


def _mock_bedrock_text_response(text: str) -> dict:
    return {
        "body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {
                        "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn",
                    }
                ).encode()
            )
        )
    }


def _mock_bedrock_tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "toolu_01") -> dict:
    return {
        "body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_use_id,
                                "name": tool_name,
                                "input": tool_input,
                            }
                        ],
                        "stop_reason": "tool_use",
                    }
                ).encode()
            )
        )
    }


class TestFulfillmentCallsBedrock:
    """The code-hook calls Bedrock InvokeModel with the verification prompt."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_fulfillment_calls_bedrock_with_verification_prompt(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Hi there! I'd be happy to help verify your identity. Could you please tell me your first and last name?"
        )

        event = _make_lex_event(
            input_transcript="hello",
            session_attributes={
                "pf_org_uuid": "b4ab304f-d1ac-4565-8dca-992b589422a7",
                "caller_phone": "+17163619276",
                "call_id": "contact-abc",
            },
        )
        handler(event, {})

        mock_client.invoke_model.assert_called_once()
        call_args = mock_client.invoke_model.call_args
        body = json.loads(call_args[1]["body"])

        system_text = " ".join(msg.get("text", "") for msg in body["system"] if isinstance(msg, dict))
        assert "verify" in system_text.lower()
        assert "b4ab304f-d1ac-4565-8dca-992b589422a7" in system_text
        assert "+17163619276" in system_text
        assert "contact-abc" in system_text
        assert body["messages"][-1]["role"] == "user"
        assert body["messages"][-1]["content"][0]["text"] == "hello"

    @patch("lex_code_hook.handler._get_bedrock")
    def test_fulfillment_returns_elicit_intent_to_continue_conversation(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Could you tell me your name?"
        )

        event = _make_lex_event(
            input_transcript="hi I need help",
            session_attributes={"pf_org_uuid": "test-uuid"},
        )
        result = handler(event, {})

        assert result["sessionState"]["dialogAction"]["type"] == "ElicitIntent"
        assert result["messages"][0]["content"] == "Could you tell me your name?"
        assert result["messages"][0]["contentType"] == "PlainText"

    @patch("lex_code_hook.handler._get_bedrock")
    def test_conversation_history_accumulates_in_session_attributes(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "What is your date of birth?"
        )

        history = json.dumps([
            {"role": "user", "content": [{"type": "text", "text": "My name is Mohit Durve"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Thank you Mohit. What is your date of birth?"}]},
        ])
        event = _make_lex_event(
            input_transcript="June 9th 1991",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "conversation_history": history,
            },
        )
        result = handler(event, {})

        saved_history = json.loads(
            result["sessionState"]["sessionAttributes"]["conversation_history"]
        )
        assert len(saved_history) == 4
        assert saved_history[-2]["role"] == "user"
        assert saved_history[-2]["content"][0]["text"] == "June 9th 1991"
        assert saved_history[-1]["role"] == "assistant"


class TestToolExecution:
    """When Claude requests a tool call, the code-hook executes it."""

    @patch("lex_code_hook.handler._execute_tool")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_lookup_patient_tool_call_is_executed(self, mock_get_bedrock, mock_execute_tool):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        tool_input = {
            "practice_id": "test-uuid",
            "call_id": "contact-123",
            "caller_phone": "+17163619276",
            "name_first": "Mohit",
            "name_last": "Durve",
            "date_of_birth": "1991-06-09",
        }
        tool_result = {
            "status": "candidates",
            "candidates": [
                {
                    "patient_id": "pat-1",
                    "name_first": "Mohit",
                    "name_last": "Durve",
                    "date_of_birth": "1991-06-09",
                    "phone_masked": "9276",
                    "probe_origin": "telecom",
                }
            ],
            "probes_tried": ["Patient?telecom=+17163619276"],
        }
        mock_execute_tool.return_value = tool_result

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response("lookup_patient", tool_input),
            _mock_bedrock_text_response(
                "I've verified your identity, Mohit. How can I help you today?"
            ),
        ]

        event = _make_lex_event(
            input_transcript="June 9th 1991",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+17163619276",
                "call_id": "contact-123",
                "conversation_history": json.dumps([
                    {"role": "user", "content": [{"type": "text", "text": "My name is Mohit Durve"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "And your date of birth?"}]},
                ]),
            },
        )
        result = handler(event, {})

        call_args = mock_execute_tool.call_args
        assert call_args[0][0] == "lookup_patient"
        assert call_args[0][1] == tool_input
        assert result["messages"][0]["content"] == "I've verified your identity, Mohit. How can I help you today?"

    @patch("lex_code_hook.handler._execute_tool")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_tool_result_fed_back_to_claude(self, mock_get_bedrock, mock_execute_tool):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        mock_execute_tool.return_value = {"status": "candidates", "candidates": [], "probes_tried": []}

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response("lookup_patient", {"practice_id": "x", "call_id": "c", "caller_phone": "+1"}),
            _mock_bedrock_text_response("I couldn't find you. Could you say your name again?"),
        ]

        event = _make_lex_event(
            input_transcript="test",
            session_attributes={"pf_org_uuid": "x", "caller_phone": "+1", "call_id": "c"},
        )
        handler(event, {})

        second_call_body = json.loads(mock_client.invoke_model.call_args_list[1][1]["body"])
        tool_result_msg = second_call_body["messages"][-1]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"


class TestCloseConversation:
    """When Claude signals the conversation is done, return Close."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_escalation_returns_close_failed(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Let me transfer you to someone who can help."
        )

        event = _make_lex_event(
            input_transcript="I want to talk to a person",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "conversation_state": "escalating",
            },
        )

        with patch("lex_code_hook.handler._should_close") as mock_should_close:
            mock_should_close.return_value = True
            result = handler(event, {})

        assert result["sessionState"]["dialogAction"]["type"] == "Close"


class TestSessionAttributePreservation:
    """Session attributes (including pf_org_uuid) must survive every turn."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_pf_org_uuid_preserved(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response("Hi!")

        event = _make_lex_event(
            input_transcript="hello",
            session_attributes={
                "pf_org_uuid": "b4ab304f-d1ac-4565-8dca-992b589422a7",
                "caller_phone": "+17163619276",
                "call_id": "contact-abc",
            },
        )
        result = handler(event, {})

        attrs = result["sessionState"]["sessionAttributes"]
        assert attrs["pf_org_uuid"] == "b4ab304f-d1ac-4565-8dca-992b589422a7"
        assert attrs["caller_phone"] == "+17163619276"
        assert attrs["call_id"] == "contact-abc"


class TestResponseStructure:
    """Every response must be valid Lex V2 format."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_response_has_required_lex_fields(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response("Hello!")

        event = _make_lex_event(input_transcript="hi", session_attributes={"pf_org_uuid": "x"})
        result = handler(event, {})

        assert "sessionState" in result
        assert "dialogAction" in result["sessionState"]
        assert "type" in result["sessionState"]["dialogAction"]
        assert "messages" in result
        assert result["messages"][0]["contentType"] == "PlainText"


class TestCompleteVerification:
    """complete_verification tool sets session attrs for phase 2."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_complete_verification_sets_session_attrs(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response(
                "complete_verification", {"patient_id": "pat-1"}
            ),
            _mock_bedrock_text_response(
                "I've confirmed your identity. How can I help you today?"
            ),
        ]

        event = _make_lex_event(
            input_transcript="yes that's correct",
            session_attributes={"pf_org_uuid": "test-uuid", "caller_phone": "+1", "call_id": "c"},
        )
        result = handler(event, {})

        attrs = result["sessionState"]["sessionAttributes"]
        assert attrs["verified_patient_id"] == "pat-1"
        assert attrs["conversation_phase"] == "service"


class TestFhirQueryGate:
    """fhir_query is rejected before verification completes."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_fhir_query_rejected_without_service_phase(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response(
                "fhir_query",
                {"practice_id": "x", "call_id": "c", "patient_id": "p", "resource_type": "DiagnosticReport"},
            ),
            _mock_bedrock_text_response("Let me verify your identity first."),
        ]

        event = _make_lex_event(
            input_transcript="are my labs back?",
            session_attributes={"pf_org_uuid": "test-uuid", "caller_phone": "+1", "call_id": "c"},
        )
        handler(event, {})

        second_call_body = json.loads(mock_client.invoke_model.call_args_list[1][1]["body"])
        tool_result_msg = second_call_body["messages"][-1]
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        content = json.loads(tool_result_msg["content"][0]["content"])
        assert content["status"] == "error"


class TestHistoryIntegrity:
    """Conversation history must preserve tool_use/tool_result pairs."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_tool_use_pairs_saved_in_history(self, mock_get_bedrock):
        """When Claude calls a tool, the history should include the
        tool_use assistant message AND the tool_result user message."""
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response(
                "complete_verification", {"patient_id": "pat-1"}
            ),
            _mock_bedrock_text_response("I've confirmed your identity."),
        ]

        event = _make_lex_event(
            input_transcript="yes",
            session_attributes={"pf_org_uuid": "x", "caller_phone": "+1", "call_id": "c"},
        )
        result = handler(event, {})

        history = json.loads(
            result["sessionState"]["sessionAttributes"]["conversation_history"]
        )
        has_tool_use = any(
            msg.get("role") == "assistant"
            and any(b.get("type") == "tool_use" for b in msg.get("content", []))
            for msg in history
        )
        has_tool_result = any(
            msg.get("role") == "user"
            and any(b.get("type") == "tool_result" for b in msg.get("content", []))
            for msg in history
        )
        assert has_tool_use, "History should contain tool_use blocks"
        assert has_tool_result, "History should contain tool_result blocks"

    @patch("lex_code_hook.handler._get_bedrock")
    def test_history_with_tools_loadable_on_next_turn(self, mock_get_bedrock):
        """History from a tool-calling turn should be loadable on the next turn
        without causing Bedrock validation errors."""
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        # Turn 1: tool call
        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response(
                "complete_verification", {"patient_id": "pat-1"}
            ),
            _mock_bedrock_text_response("Verified. How can I help?"),
        ]
        event1 = _make_lex_event(
            input_transcript="yes",
            session_attributes={"pf_org_uuid": "x", "caller_phone": "+1", "call_id": "c"},
        )
        result1 = handler(event1, {})
        saved_attrs = result1["sessionState"]["sessionAttributes"]

        # Turn 2: uses the history from turn 1
        mock_client.invoke_model.reset_mock()
        mock_client.invoke_model.side_effect = None
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Let me check on that."
        )
        event2 = _make_lex_event(
            input_transcript="are my labs back?",
            session_attributes=saved_attrs,
        )
        result2 = handler(event2, {})

        # Should succeed — no validation error
        assert result2["sessionState"]["dialogAction"]["type"] == "ElicitIntent"
        # Verify the messages sent to Claude include prior tool context
        call_body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        messages = call_body["messages"]
        assert len(messages) >= 4  # prior history + new user turn

    def test_sanitize_removes_orphaned_tool_use(self):
        from lex_code_hook.handler import _sanitize_history

        orphaned = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
            # Missing tool_result!
            {"role": "user", "content": [{"type": "text", "text": "hello?"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "sorry"}]},
        ]
        clean = _sanitize_history(orphaned)
        tool_use_count = sum(
            1 for m in clean if m.get("role") == "assistant"
            and any(b.get("type") == "tool_use" for b in m.get("content", []))
        )
        assert tool_use_count == 0, "Orphaned tool_use should be removed"
        assert len(clean) == 3  # user "hi", user "hello?", assistant "sorry"

    def test_sanitize_keeps_valid_tool_pairs(self):
        from lex_code_hook.handler import _sanitize_history

        valid = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ]
        clean = _sanitize_history(valid)
        assert len(clean) == 4, "Valid tool pairs should be preserved"


class TestCloseFulfilled:
    """After service phase, graceful goodbye returns Close(Fulfilled)."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_goodbye_in_service_phase_closes_fulfilled(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Thank you for calling. Goodbye."
        )

        event = _make_lex_event(
            input_transcript="no that's all thank you",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+1",
                "call_id": "c",
                "conversation_phase": "service",
                "verified_patient_id": "pat-1",
            },
        )
        result = handler(event, {})

        assert result["sessionState"]["dialogAction"]["type"] == "Close"
        assert result["sessionState"]["intent"]["state"] == "Fulfilled"


class TestPromptHardening:
    """Phase 1: safety hardening (emergency, after-hours, non-English, sensitive dx, minors)."""

    def test_prompt_contains_emergency_detection(self):
        from lex_code_hook.handler import _load_system_prompt
        prompt = _load_system_prompt()
        assert "911" in prompt
        assert "emergency" in prompt.lower()
        assert "chest pain" in prompt.lower()

    def test_prompt_contains_after_hours_handling(self):
        from lex_code_hook.handler import _load_system_prompt
        prompt = _load_system_prompt()
        assert "business_hours_status" in prompt
        assert "closed" in prompt.lower()

    def test_prompt_contains_non_english_handling(self):
        from lex_code_hook.handler import _load_system_prompt
        prompt = _load_system_prompt()
        assert "language_barrier" in prompt

    def test_prompt_contains_sensitive_diagnosis_gating(self):
        from lex_code_hook.handler import _load_system_prompt
        prompt = _load_system_prompt()
        assert "HIV" in prompt or "psychiatric" in prompt.lower()
        assert "patient portal" in prompt.lower()

    def test_prompt_contains_minor_guardian_handling(self):
        from lex_code_hook.handler import _load_system_prompt
        prompt = _load_system_prompt()
        assert "guardian" in prompt.lower()

    def test_escalation_reasons_include_emergency(self):
        from lex_code_hook.handler import _TOOL_DEFINITIONS
        escalate_def = next(t for t in _TOOL_DEFINITIONS if t["name"] == "escalate_to_human")
        reason_desc = escalate_def["input_schema"]["properties"]["reason"]["description"]
        assert "emergency" in reason_desc

    def test_escalation_reasons_include_language_barrier(self):
        from lex_code_hook.handler import _TOOL_DEFINITIONS
        escalate_def = next(t for t in _TOOL_DEFINITIONS if t["name"] == "escalate_to_human")
        reason_desc = escalate_def["input_schema"]["properties"]["reason"]["description"]
        assert "language_barrier" in reason_desc

    @patch("lex_code_hook.handler._get_bedrock")
    def test_after_hours_closed_injects_status_into_prompt(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Our office is currently closed."
        )

        event = _make_lex_event(
            input_transcript="hello",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+17163619276",
                "call_id": "contact-abc",
                "business_hours_status": "closed",
                "business_hours_display": "Mon-Fri 8am-5pm",
            },
        )
        handler(event, {})

        call_body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        system_text = " ".join(msg.get("text", "") for msg in call_body["system"] if isinstance(msg, dict))
        assert "business_hours_status: closed" in system_text
        assert "Mon-Fri 8am-5pm" in system_text

    @patch("lex_code_hook.handler._get_bedrock")
    def test_no_business_hours_defaults_to_open(self, mock_get_bedrock):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response("Hi!")

        event = _make_lex_event(
            input_transcript="hello",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+1",
                "call_id": "c",
            },
        )
        handler(event, {})

        call_body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        system_text = " ".join(msg.get("text", "") for msg in call_body["system"] if isinstance(msg, dict))
        assert "business_hours_status: open" in system_text


class TestCallRecord:
    """Phase 2: call record written to DDB on Close."""

    @patch("lex_code_hook.handler._write_call_record")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_close_fulfilled_writes_call_record(self, mock_get_bedrock, mock_write):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Thank you for calling. Goodbye."
        )

        event = _make_lex_event(
            input_transcript="no that's all thank you",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+17163619276",
                "call_id": "contact-abc",
                "conversation_phase": "service",
                "verified_patient_id": "pat-1",
            },
        )
        handler(event, {})
        mock_write.assert_called_once()
        call_args = mock_write.call_args[0][0]
        assert call_args["practice_id"] == "test-uuid"
        assert call_args["call_id"] == "contact-abc"
        assert call_args["outcome"] == "fulfilled"

    @patch("lex_code_hook.handler._write_call_record")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_close_escalation_writes_call_record(self, mock_get_bedrock, mock_write):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Let me transfer you."
        )

        event = _make_lex_event(
            input_transcript="I want to talk to a person",
            session_attributes={
                "pf_org_uuid": "test-uuid",
                "caller_phone": "+1",
                "call_id": "contact-esc",
                "conversation_state": "escalating",
            },
        )
        handler(event, {})
        mock_write.assert_called_once()
        call_args = mock_write.call_args[0][0]
        assert call_args["outcome"] == "escalated"

    @patch("lex_code_hook.handler._write_call_record")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_escalation_reason_stored_in_call_record(self, mock_get_bedrock, mock_write):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client

        mock_client.invoke_model.side_effect = [
            _mock_bedrock_tool_use_response(
                "escalate_to_human", {"reason": "emergency"}
            ),
            _mock_bedrock_text_response(
                "If this is a medical emergency, please hang up and dial 911."
            ),
        ]

        event = _make_lex_event(
            input_transcript="I'm having chest pain",
            session_attributes={"pf_org_uuid": "test-uuid", "caller_phone": "+1", "call_id": "c"},
        )
        handler(event, {})
        mock_write.assert_called_once()
        call_args = mock_write.call_args[0][0]
        assert call_args["escalation_reason"] == "emergency"

    @patch("lex_code_hook.handler._write_call_record")
    @patch("lex_code_hook.handler._get_bedrock")
    def test_elicit_intent_does_not_write_call_record(self, mock_get_bedrock, mock_write):
        from lex_code_hook.handler import handler

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response(
            "Could you tell me your name?"
        )

        event = _make_lex_event(
            input_transcript="hello",
            session_attributes={"pf_org_uuid": "test-uuid", "caller_phone": "+1", "call_id": "c"},
        )
        handler(event, {})
        mock_write.assert_not_called()


class TestMaxTurns:
    """Safety: if conversation exceeds max turns, close gracefully."""

    @patch("lex_code_hook.handler._get_bedrock")
    def test_max_turns_triggers_close(self, mock_get_bedrock):
        from lex_code_hook.handler import handler, MAX_TURNS

        mock_client = MagicMock()
        mock_get_bedrock.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_bedrock_text_response("test")

        long_history = []
        for i in range(MAX_TURNS):
            long_history.append({"role": "user", "content": [{"type": "text", "text": f"turn {i}"}]})
            long_history.append({"role": "assistant", "content": [{"type": "text", "text": f"reply {i}"}]})

        event = _make_lex_event(
            input_transcript="one more",
            session_attributes={
                "pf_org_uuid": "x",
                "conversation_history": json.dumps(long_history),
            },
        )
        result = handler(event, {})

        assert result["sessionState"]["dialogAction"]["type"] == "Close"
        assert "transfer" in result["messages"][0]["content"].lower() or "help" in result["messages"][0]["content"].lower()
