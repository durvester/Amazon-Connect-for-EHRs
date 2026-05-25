"""Tests for the Connect DID claim (Session 0008).

The provisioner wraps two Connect API calls:

  1. SearchAvailablePhoneNumbersV2  — find one unclaimed US DID
  2. ClaimPhoneNumber                — bind it to our Connect instance

Both calls are subject to AWS-side throttling (~1-2/s observed for
claim). Tests verify the happy path, surface throttling as a typed
error so the API layer can return 503 + retry-after, and refuse to
claim when no numbers come back.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from routing.connect_provisioner import (
    ConnectProvisioner,
    PhoneProvisionerError,
    PhoneProvisionerThrottled,
    NoPhoneNumbersAvailable,
)

INSTANCE_ID = "11111111-2222-3333-4444-555555555555"
INSTANCE_ARN = f"arn:aws:connect:us-east-1:000000000000:instance/{INSTANCE_ID}"


def _client_with_search_then_claim(claimed_did="+15551234567"):
    client = MagicMock()
    client.search_available_phone_numbers_v2.return_value = {
        "AvailablePhoneNumbersList": [
            {
                "PhoneNumber": claimed_did,
                "PhoneNumberCountryCode": "US",
                "PhoneNumberType": "DID",
            }
        ]
    }
    client.claim_phone_number.return_value = {
        "PhoneNumberId": "pn-abc",
        "PhoneNumberArn": f"arn:aws:connect:us-east-1:0:phone-number/{claimed_did}",
    }
    return client


def test_claims_first_available_did():
    client = _client_with_search_then_claim("+15551234567")
    p = ConnectProvisioner(connect_client=client, instance_arn=INSTANCE_ARN)
    did = p.claim_did(connect_instance_id=INSTANCE_ID)
    assert did == "+15551234567"

    search_kwargs = client.search_available_phone_numbers_v2.call_args.kwargs
    assert search_kwargs["TargetArn"] == INSTANCE_ARN
    assert search_kwargs["PhoneNumberCountryCode"] == "US"
    assert search_kwargs["PhoneNumberType"] == "DID"

    claim_kwargs = client.claim_phone_number.call_args.kwargs
    assert claim_kwargs["TargetArn"] == INSTANCE_ARN
    assert claim_kwargs["PhoneNumber"] == "+15551234567"


def test_raises_when_no_numbers_available():
    client = MagicMock()
    client.search_available_phone_numbers_v2.return_value = {
        "AvailablePhoneNumbersList": []
    }
    p = ConnectProvisioner(connect_client=client, instance_arn=INSTANCE_ARN)
    with pytest.raises(NoPhoneNumbersAvailable):
        p.claim_did(connect_instance_id=INSTANCE_ID)
    client.claim_phone_number.assert_not_called()


def test_throttling_during_search_is_typed():
    client = MagicMock()
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "SearchAvailablePhoneNumbersV2",
    )
    client.search_available_phone_numbers_v2.side_effect = err
    p = ConnectProvisioner(connect_client=client, instance_arn=INSTANCE_ARN)
    with pytest.raises(PhoneProvisionerThrottled):
        p.claim_did(connect_instance_id=INSTANCE_ID)


def test_throttling_during_claim_is_typed():
    client = _client_with_search_then_claim()
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "ClaimPhoneNumber",
    )
    client.claim_phone_number.side_effect = err
    p = ConnectProvisioner(connect_client=client, instance_arn=INSTANCE_ARN)
    with pytest.raises(PhoneProvisionerThrottled):
        p.claim_did(connect_instance_id=INSTANCE_ID)


def test_other_client_errors_surface_as_provisioner_error():
    client = _client_with_search_then_claim()
    err = ClientError(
        {"Error": {"Code": "InvalidParameterException", "Message": "bad"}},
        "ClaimPhoneNumber",
    )
    client.claim_phone_number.side_effect = err
    p = ConnectProvisioner(connect_client=client, instance_arn=INSTANCE_ARN)
    with pytest.raises(PhoneProvisionerError):
        p.claim_did(connect_instance_id=INSTANCE_ID)
