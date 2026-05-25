"""Tests for the KMS-encrypted DDB token store.

Uses `moto` to mock both DynamoDB and KMS. Round-trips token records and
asserts the on-disk DDB item never contains the plaintext token bytes.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from oauth.token_store import TokenStore, TokenStoreError, TokenRecord

TABLE = "oauth-tokens-test"
KEY_ALIAS = "alias/oauth-tokens-test"


def _bootstrap_kms_and_ddb():
    """Create a CMK + DDB table inside the active moto context."""
    kms = boto3.client("kms", region_name="us-east-1")
    cmk = kms.create_key(Description="test")["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName=KEY_ALIAS, TargetKeyId=cmk)

    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "practice_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "practice_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return cmk


@mock_aws
def test_put_then_get_roundtrips():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")

    store.put(
        practice_id="pf-001",
        access_token="access-abc",
        refresh_token="refresh-xyz",
        expires_at=1_700_000_300,
    )

    rec = store.get("pf-001")
    assert isinstance(rec, TokenRecord)
    assert rec.practice_id == "pf-001"
    assert rec.access_token == "access-abc"
    assert rec.refresh_token == "refresh-xyz"
    assert rec.expires_at == 1_700_000_300
    assert rec.status == "active"


@mock_aws
def test_get_missing_returns_none():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")
    assert store.get("does-not-exist") is None


@mock_aws
def test_ddb_item_does_not_contain_plaintext_tokens():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")

    store.put(
        practice_id="pf-001",
        access_token="SECRET-ACCESS-TOKEN-PLAINTEXT",
        refresh_token="SECRET-REFRESH-TOKEN-PLAINTEXT",
        expires_at=1_700_000_300,
    )

    raw_item = boto3.client("dynamodb", region_name="us-east-1").get_item(
        TableName=TABLE,
        Key={"practice_id": {"S": "pf-001"}},
    )["Item"]

    # Serialize the entire item to a string and assert neither plaintext appears.
    blob = repr(raw_item)
    assert "SECRET-ACCESS-TOKEN-PLAINTEXT" not in blob
    assert "SECRET-REFRESH-TOKEN-PLAINTEXT" not in blob
    # The ciphertext fields exist and are binary.
    assert "access_token_ciphertext" in raw_item
    assert "refresh_token_ciphertext" in raw_item
    assert "B" in raw_item["access_token_ciphertext"]


@mock_aws
def test_put_overwrites_existing_row():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")

    store.put("pf-001", "a1", "r1", expires_at=1_000)
    store.put("pf-001", "a2", "r2", expires_at=2_000)

    rec = store.get("pf-001")
    assert rec.access_token == "a2"
    assert rec.refresh_token == "r2"
    assert rec.expires_at == 2_000


@mock_aws
def test_records_last_refreshed_at_timestamp():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")
    store.put("pf-001", "a", "r", expires_at=1_700_000_300)
    rec = store.get("pf-001")
    assert rec.last_refreshed_at > 0


@mock_aws
def test_status_can_be_marked_needs_reconnect():
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")
    store.put("pf-001", "a", "r", expires_at=1_700_000_300)
    store.mark_needs_reconnect("pf-001")
    assert store.get("pf-001").status == "needs_reconnect"


@mock_aws
def test_get_with_corrupted_ciphertext_raises():
    cmk = _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")

    # Write garbage ciphertext bypassing the store's encrypt path.
    boto3.client("dynamodb", region_name="us-east-1").put_item(
        TableName=TABLE,
        Item={
            "practice_id": {"S": "pf-bad"},
            "access_token_ciphertext": {"B": b"not-valid-kms-ciphertext"},
            "refresh_token_ciphertext": {"B": b"not-valid-kms-ciphertext"},
            "expires_at": {"N": "0"},
            "last_refreshed_at": {"N": "0"},
            "status": {"S": "active"},
        },
    )

    with pytest.raises(TokenStoreError):
        store.get("pf-bad")
    # silence unused-var lint
    _ = cmk


@mock_aws
def test_update_access_token_rewrites_access_only():
    """The no-rotation refresh path: only access_token + expires_at change,
    refresh_token row is preserved untouched.
    """
    _bootstrap_kms_and_ddb()
    store = TokenStore(table_name=TABLE, key_id=KEY_ALIAS, region="us-east-1")
    store.put("pf-001", access_token="old-a", refresh_token="rt-stable", expires_at=1000)

    store.update_access_token("pf-001", "new-a", expires_at=2000)

    rec = store.get("pf-001")
    assert rec is not None
    assert rec.access_token == "new-a"
    assert rec.expires_at == 2000
    assert rec.refresh_token == "rt-stable"   # unchanged
    assert rec.status == "active"
