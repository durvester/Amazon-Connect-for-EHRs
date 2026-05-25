"""Claim a fresh US DID and bind it to our Connect instance (Session 0008).

Two API calls in sequence:

    SearchAvailablePhoneNumbersV2 — list one unclaimed US DID for the
                                    target Connect instance ARN
    ClaimPhoneNumber              — bind that DID to the instance

The boto3 client is injected so unit tests can drive it deterministically;
production code constructs the client from boto3 in the API layer.

Throttling lifecycle (ADR-0014 cost note + Session 0007 OQ #4):
ClaimPhoneNumber is rate-limited by AWS at ~1-2 RPS. The API layer
catches ``PhoneProvisionerThrottled`` and returns 503 with a
retry-after header — bulk onboarding chunks at the API edge, not here.
"""

from __future__ import annotations

from botocore.exceptions import ClientError


_THROTTLING_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestThrottledException",
    "Throttling",
}


class PhoneProvisionerError(RuntimeError):
    """Base for any failure in the DID claim flow."""


class PhoneProvisionerThrottled(PhoneProvisionerError):
    """Raised when AWS Connect returns a throttling error.

    The caller should back off and retry. The API layer surfaces this
    as 503 + Retry-After to the onboarding client.
    """


class NoPhoneNumbersAvailable(PhoneProvisionerError):
    """Raised when Connect has no claimable US DIDs at the moment.

    Distinct from throttling — this means the pool was empty, not
    that we got rate-limited. Re-running might succeed once new
    inventory arrives, but not immediately.
    """


class ConnectProvisioner:
    def __init__(
        self,
        *,
        connect_client,
        instance_arn: str,
        country_code: str = "US",
        phone_number_type: str = "DID",
    ):
        self._connect = connect_client
        self._instance_arn = instance_arn
        self._country = country_code
        self._type = phone_number_type

    def claim_did(self, *, connect_instance_id: str) -> str:
        """Search for one available DID and claim it. Returns the E.164 number.

        ``connect_instance_id`` is accepted (and audit-logged by the caller)
        but the underlying API uses the ARN, which is constructed once at
        provisioner-construction time.
        """
        try:
            search = self._connect.search_available_phone_numbers_v2(
                TargetArn=self._instance_arn,
                PhoneNumberCountryCode=self._country,
                PhoneNumberType=self._type,
                MaxResults=1,
            )
        except ClientError as e:
            _reraise_throttled_or(e, "search_available_phone_numbers_v2")

        numbers = search.get("AvailablePhoneNumbersList") or []
        if not numbers:
            raise NoPhoneNumbersAvailable(
                f"no available {self._country} {self._type} numbers for "
                f"instance {connect_instance_id}"
            )

        did = numbers[0]["PhoneNumber"]
        try:
            self._connect.claim_phone_number(
                TargetArn=self._instance_arn,
                PhoneNumber=did,
            )
        except ClientError as e:
            _reraise_throttled_or(e, "claim_phone_number")
        return did


def _reraise_throttled_or(exc: ClientError, op: str) -> None:
    code = exc.response.get("Error", {}).get("Code")
    if code in _THROTTLING_CODES:
        raise PhoneProvisionerThrottled(f"{op} throttled: {exc}") from exc
    raise PhoneProvisionerError(f"{op} failed: {exc}") from exc
