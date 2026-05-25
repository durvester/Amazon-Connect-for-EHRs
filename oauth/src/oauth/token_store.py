"""KMS-encrypted DynamoDB store for per-practice OAuth tokens.

The on-disk DDB item never contains plaintext access or refresh tokens —
those go through AWS KMS Encrypt/Decrypt on every write/read. DDB SSE-KMS
adds at-rest encryption on top; app-layer KMS gives a second envelope so
the tokens are unreadable even by anyone with raw DDB access.

Schema (matches `docs/architecture.md` "oauth-tokens" table):

    practice_id (PK)            : S
    access_token_ciphertext     : B   (KMS-encrypted blob)
    refresh_token_ciphertext    : B   (KMS-encrypted blob)
    expires_at                  : N   (epoch seconds — access token)
    last_refreshed_at           : N   (epoch seconds)
    status                      : S   ("active" | "needs_reconnect")
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError


class TokenStoreError(RuntimeError):
    """Raised on any KMS/DDB error or malformed stored row."""


@dataclass(frozen=True)
class TokenRecord:
    practice_id: str
    access_token: str
    refresh_token: str
    expires_at: int
    last_refreshed_at: int
    status: str


class TokenStore:
    def __init__(self, *, table_name: str, key_id: str, region: str = "us-east-1"):
        self._table_name = table_name
        self._key_id = key_id
        self._ddb = boto3.client("dynamodb", region_name=region)
        self._kms = boto3.client("kms", region_name=region)

    def _encrypt(self, plaintext: str) -> bytes:
        try:
            resp = self._kms.encrypt(
                KeyId=self._key_id,
                Plaintext=plaintext.encode("utf-8"),
            )
        except ClientError as e:
            raise TokenStoreError(f"KMS encrypt failed: {e}") from e
        return resp["CiphertextBlob"]

    def _decrypt(self, ciphertext: bytes) -> str:
        try:
            resp = self._kms.decrypt(CiphertextBlob=ciphertext)
        except ClientError as e:
            raise TokenStoreError(f"KMS decrypt failed: {e}") from e
        return resp["Plaintext"].decode("utf-8")

    def put(
        self,
        practice_id: str,
        access_token: str,
        refresh_token: str,
        *,
        expires_at: int,
    ) -> None:
        item = {
            "practice_id": {"S": practice_id},
            "access_token_ciphertext": {"B": self._encrypt(access_token)},
            "refresh_token_ciphertext": {"B": self._encrypt(refresh_token)},
            "expires_at": {"N": str(int(expires_at))},
            "last_refreshed_at": {"N": str(int(time.time()))},
            "status": {"S": "active"},
        }
        try:
            self._ddb.put_item(TableName=self._table_name, Item=item)
        except ClientError as e:
            raise TokenStoreError(f"DDB put failed: {e}") from e

    def get(self, practice_id: str) -> TokenRecord | None:
        try:
            resp = self._ddb.get_item(
                TableName=self._table_name,
                Key={"practice_id": {"S": practice_id}},
            )
        except ClientError as e:
            raise TokenStoreError(f"DDB get failed: {e}") from e
        item = resp.get("Item")
        if not item:
            return None
        return TokenRecord(
            practice_id=item["practice_id"]["S"],
            access_token=self._decrypt(item["access_token_ciphertext"]["B"]),
            refresh_token=self._decrypt(item["refresh_token_ciphertext"]["B"]),
            expires_at=int(item["expires_at"]["N"]),
            last_refreshed_at=int(item["last_refreshed_at"]["N"]),
            status=item["status"]["S"],
        )

    def update_access_token(
        self,
        practice_id: str,
        access_token: str,
        *,
        expires_at: int,
    ) -> None:
        """Partial-update path for the no-rotation refresh case.

        Session 0004 finding: PF doesn't rotate refresh tokens. When the
        near-expiry refresh in Session 0006's `_get_credentials` returns
        the same refresh_token we sent, we only need to rewrite the access
        token + expires_at. One UpdateItem, one KMS Encrypt, no churn on
        the refresh_token_ciphertext column.
        """
        try:
            self._ddb.update_item(
                TableName=self._table_name,
                Key={"practice_id": {"S": practice_id}},
                UpdateExpression=(
                    "SET access_token_ciphertext = :c, "
                    "expires_at = :e, "
                    "last_refreshed_at = :r"
                ),
                ExpressionAttributeValues={
                    ":c": {"B": self._encrypt(access_token)},
                    ":e": {"N": str(int(expires_at))},
                    ":r": {"N": str(int(time.time()))},
                },
            )
        except ClientError as e:
            raise TokenStoreError(f"DDB update failed: {e}") from e

    def mark_needs_reconnect(self, practice_id: str) -> None:
        try:
            self._ddb.update_item(
                TableName=self._table_name,
                Key={"practice_id": {"S": practice_id}},
                UpdateExpression="SET #s = :v",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":v": {"S": "needs_reconnect"}},
            )
        except ClientError as e:
            raise TokenStoreError(f"DDB update failed: {e}") from e
