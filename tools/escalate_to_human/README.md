# tools/escalate_to_human

Lambda tool the agent calls when it cannot verify after `max_verification_attempts` (default 3) or when the caller asks for a person. Sets `escalate=true` on the Connect contact; contact flow routes to the escalation queue.

**Status:** scaffold. Implemented in Session 0004.
