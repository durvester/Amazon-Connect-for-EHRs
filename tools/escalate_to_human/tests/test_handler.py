"""Tests for escalate_to_human handler (ADR-0019)."""


def test_handler_returns_escalated_with_reason():
    from escalate_to_human.handler import handler

    result = handler({"reason": "no_match"}, None)
    assert result["status"] == "escalated"
    assert result["reason"] == "no_match"


def test_handler_defaults_reason_to_unknown():
    from escalate_to_human.handler import handler

    result = handler({}, None)
    assert result["status"] == "escalated"
    assert result["reason"] == "unknown"


def test_handler_preserves_extra_fields():
    from escalate_to_human.handler import handler

    result = handler({"reason": "caller_request", "call_id": "c-123"}, None)
    assert result["status"] == "escalated"
    assert result["reason"] == "caller_request"
