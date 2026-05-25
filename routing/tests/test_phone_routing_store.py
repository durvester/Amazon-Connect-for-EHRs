"""Unit tests for ``routing.phone_routing_store``.

These tests are the multi-tenancy contract (ADR-0014). The contact
flow reads from this store on every inbound call; the onboarding API
writes to it on every new practice. Both code paths share these test
guarantees.
"""

from __future__ import annotations

import pytest
import boto3
from moto import mock_aws

from routing import (
    PhoneNumberAlreadyClaimed,
    PhoneNumberNotFound,
    PhoneRoutingRecord,
    PhoneRoutingStore,
)


TABLE_NAME = "pf-voice-qa-phone-routing"
REGION = "us-east-1"


def _create_table(ddb) -> None:
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[{"AttributeName": "phone_number", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "phone_number", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def store():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        yield PhoneRoutingStore(table_name=TABLE_NAME, region=REGION)


def test_claim_writes_active_row_and_resolve_returns_practice_id(store):
    store.claim(
        phone_number="+15551234567",
        practice_id="pf-practice-abc",
        connect_instance_id="abcd-1234",
    )
    assert store.resolve("+15551234567") == "pf-practice-abc"


def test_resolve_returns_none_for_unknown_number(store):
    assert store.resolve("+15559999999") is None


def test_claim_is_idempotent_for_identical_inputs(store):
    """Claiming the same DID for the same practice twice is a no-op,
    not an error. Onboarding retries shouldn't blow up."""
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    assert store.resolve("+15551234567") == "pf-practice-abc"


def test_claim_rejects_double_claim_for_different_practice(store):
    """A DID claimed by practice A must not be silently reassigned to
    practice B. Onboarding bugs should surface as exceptions."""
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    with pytest.raises(PhoneNumberAlreadyClaimed):
        store.claim("+15551234567", "pf-practice-xyz", "abcd-1234")


def test_release_marks_row_inactive_and_resolve_returns_none(store):
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    store.release("+15551234567")
    assert store.resolve("+15551234567") is None


def test_release_unknown_number_raises(store):
    with pytest.raises(PhoneNumberNotFound):
        store.release("+15559999999")


def test_get_record_returns_full_row(store):
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    rec = store.get_record("+15551234567")
    assert isinstance(rec, PhoneRoutingRecord)
    assert rec.phone_number == "+15551234567"
    assert rec.practice_id == "pf-practice-abc"
    assert rec.connect_instance_id == "abcd-1234"
    assert rec.status == "active"
    assert rec.claimed_at  # ISO timestamp, present


def test_get_record_returns_released_row_with_status(store):
    """``get_record`` is the audit-friendly read: it returns the row
    even if released, so operational tools can see history.
    ``resolve`` is the call-path read: it filters to active only."""
    store.claim("+15551234567", "pf-practice-abc", "abcd-1234")
    store.release("+15551234567")
    rec = store.get_record("+15551234567")
    assert rec.status == "released"
    assert rec.practice_id == "pf-practice-abc"


def test_get_record_returns_none_for_unknown(store):
    assert store.get_record("+15559999999") is None
