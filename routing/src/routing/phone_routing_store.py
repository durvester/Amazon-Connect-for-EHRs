"""DID → practice_id resolver (ADR-0014).

The contact flow reads this at every call start via Connect's native
DynamoDB integration; the OAuth onboarding API (Session 0008) writes
to it when a practice completes onboarding. The store is the single
source of truth for the call-time tenant identifier.

Schema:
    phone_number (PK)        : S   E.164 (e.g. "+15551234567")
    practice_id              : S
    connect_instance_id      : S
    claimed_at               : S   ISO8601 UTC
    status                   : S   "active" | "released"
    released_at              : S   ISO8601 UTC (only when status="released")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import boto3
from botocore.exceptions import ClientError


Status = Literal["active", "released"]


class PhoneRoutingStoreError(RuntimeError):
    """Base for all phone-routing failures (DDB errors, malformed rows)."""


class PhoneNumberAlreadyClaimed(PhoneRoutingStoreError):
    """Raised when a DID is already claimed by a different practice.

    Idempotent re-claims by the same practice are not an error — they
    pass silently. See ADR-0014 for the lifecycle reasoning.
    """


class PhoneNumberNotFound(PhoneRoutingStoreError):
    """Raised when ``release()`` is called on a DID we never claimed.

    ``resolve()`` and ``get_record()`` return None instead of raising —
    they are read-path safe."""


@dataclass(frozen=True)
class PhoneRoutingRecord:
    phone_number: str
    practice_id: str
    connect_instance_id: str
    claimed_at: str
    status: Status
    released_at: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PhoneRoutingStore:
    def __init__(self, *, table_name: str, region: str = "us-east-1"):
        self._table_name = table_name
        self._ddb = boto3.client("dynamodb", region_name=region)

    # ─── Writes ──────────────────────────────────────────────────────

    def claim(
        self,
        phone_number: str,
        practice_id: str,
        connect_instance_id: str,
    ) -> None:
        """Claim a DID for a practice.

        Idempotent if the same (phone_number, practice_id) pair already
        exists with status="active". Raises ``PhoneNumberAlreadyClaimed``
        if the DID is bound to a different practice. Both behaviors are
        enforced via a single conditional write so the check + write is
        atomic — no race window between a check and a put.
        """
        existing = self.get_record(phone_number)
        if existing is not None:
            if existing.practice_id == practice_id and existing.status == "active":
                return  # idempotent re-claim
            raise PhoneNumberAlreadyClaimed(
                f"{phone_number!r} already claimed by "
                f"{existing.practice_id!r} (status={existing.status})"
            )

        try:
            self._ddb.put_item(
                TableName=self._table_name,
                Item={
                    "phone_number": {"S": phone_number},
                    "practice_id": {"S": practice_id},
                    "connect_instance_id": {"S": connect_instance_id},
                    "claimed_at": {"S": _now_iso()},
                    "status": {"S": "active"},
                },
                ConditionExpression="attribute_not_exists(phone_number)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Lost a race; re-read and re-evaluate.
                existing = self.get_record(phone_number)
                if existing and existing.practice_id == practice_id:
                    return
                raise PhoneNumberAlreadyClaimed(
                    f"{phone_number!r} concurrently claimed"
                ) from e
            raise PhoneRoutingStoreError(f"DDB put failed: {e}") from e

    def release(self, phone_number: str) -> None:
        """Mark a DID released. The row stays for audit; ``resolve`` will
        return None for it. Raises ``PhoneNumberNotFound`` if no row
        exists — callers should know what they're releasing."""
        try:
            self._ddb.update_item(
                TableName=self._table_name,
                Key={"phone_number": {"S": phone_number}},
                UpdateExpression="SET #s = :released, released_at = :t",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":released": {"S": "released"},
                    ":t": {"S": _now_iso()},
                },
                ConditionExpression="attribute_exists(phone_number)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise PhoneNumberNotFound(
                    f"no phone_routing row for {phone_number!r}"
                ) from e
            raise PhoneRoutingStoreError(f"DDB update failed: {e}") from e

    # ─── Reads ───────────────────────────────────────────────────────

    def resolve(self, phone_number: str) -> str | None:
        """Call-time read. Returns the active practice_id for the DID,
        or None if missing or released. Released rows are filtered so
        the contact flow can treat None as "drop the call / play
        unknown-number message"."""
        rec = self.get_record(phone_number)
        if rec is None or rec.status != "active":
            return None
        return rec.practice_id

    def get_record(self, phone_number: str) -> PhoneRoutingRecord | None:
        """Audit-friendly read. Returns the full row regardless of status,
        or None if missing. Operational tools / on-call use this; the
        call-path uses ``resolve``."""
        try:
            resp = self._ddb.get_item(
                TableName=self._table_name,
                Key={"phone_number": {"S": phone_number}},
            )
        except ClientError as e:
            raise PhoneRoutingStoreError(f"DDB get failed: {e}") from e

        item = resp.get("Item")
        if not item:
            return None

        try:
            return PhoneRoutingRecord(
                phone_number=item["phone_number"]["S"],
                practice_id=item["practice_id"]["S"],
                connect_instance_id=item["connect_instance_id"]["S"],
                claimed_at=item["claimed_at"]["S"],
                status=item["status"]["S"],  # type: ignore[arg-type]
                released_at=(
                    item["released_at"]["S"] if "released_at" in item else None
                ),
            )
        except KeyError as e:
            raise PhoneRoutingStoreError(
                f"phone_routing row {phone_number!r} missing field {e}"
            ) from e
