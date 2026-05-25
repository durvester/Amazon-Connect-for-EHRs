"""Lambda entrypoint for escalate_to_human (ADR-0019).

Returns a structured result indicating the caller should be transferred
to a human agent. The code-hook Lambda uses this result to set
conversation_state="escalating" and return Close(Failed) to Lex.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict, context: object) -> dict:
    reason = event.get("reason", "unknown")
    logger.info("escalate_to_human: reason=%s", reason)
    return {"status": "escalated", "reason": reason}
