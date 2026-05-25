"""Shared per-practice credential resolver.

Resolves (practice_id) → (fhir_base_url, access_token, refresh_callable).
Used by both lookup_patient and fhir_query handlers.

Three refresh branches (from Session 0006):
  1. No rotation (PF default) → update_access_token.
  2. Rotation detected → full put.
  3. invalid_grant → mark_needs_reconnect + CredentialsExpired.
"""

from __future__ import annotations

import os
import time
from typing import Callable

from .client_secret_provider import resolve as resolve_client_secret
from .practices_store import PracticesStore, PracticesStoreError
from .refresh import InvalidGrantError, refresh_access_token
from .token_store import TokenStore

_REFRESH_LEEWAY_SECONDS = 60


class CredentialsExpired(RuntimeError):
    """The practice's refresh token is no longer valid."""


class RefreshContext:
    """Callable that force-refreshes the access token on 401."""

    def __init__(self, do_refresh: Callable[[bool], str]):
        self._do_refresh = do_refresh

    def __call__(self) -> str:
        return self._do_refresh(True)


def _build_stores() -> tuple[PracticesStore, TokenStore]:
    region = os.environ.get("AWS_REGION") or os.environ.get(
        "AWS_DEFAULT_REGION", "us-east-1"
    )
    return (
        PracticesStore(table_name=os.environ["PRACTICES_TABLE_NAME"], region=region),
        TokenStore(
            table_name=os.environ["TOKENS_TABLE_NAME"],
            key_id=os.environ["OAUTH_KMS_KEY_ARN"],
            region=region,
        ),
    )


def get_credentials(
    practice_id: str,
    *,
    practices_store: PracticesStore | None = None,
    token_store: TokenStore | None = None,
) -> tuple[str, str, RefreshContext]:
    """Return (fhir_base_url, access_token, refresh_ctx) for a practice.

    Optional store injection for testing; defaults read from env vars.
    """
    if practices_store is None or token_store is None:
        _ps, _ts = _build_stores()
        practices_store = practices_store or _ps
        token_store = token_store or _ts

    try:
        practice = practices_store.get(practice_id)
    except PracticesStoreError as e:
        raise CredentialsExpired(str(e)) from e

    record = token_store.get(practice_id)
    if record is None or record.status != "active":
        raise CredentialsExpired(
            f"no active credentials for {practice_id} "
            f"(status={record.status if record else 'missing'})"
        )

    client_secret = resolve_client_secret(
        practice.pf_client_secret_arn,
        region=os.environ.get("AWS_REGION", "us-east-1"),
    )

    tokens = token_store

    def _do_refresh(force: bool) -> str:
        nonlocal record
        if not force and record.expires_at - int(time.time()) > _REFRESH_LEEWAY_SECONDS:
            return record.access_token

        try:
            new_ts = refresh_access_token(
                refresh_token=record.refresh_token,
                token_endpoint=practice.token_endpoint,
                client_id=practice.pf_client_id,
                client_secret=client_secret,
            )
        except InvalidGrantError as e:
            tokens.mark_needs_reconnect(practice_id)
            raise CredentialsExpired(f"refresh failed for {practice_id}") from e

        new_expires_at = int(time.time()) + new_ts.expires_in

        if new_ts.refresh_token == record.refresh_token:
            tokens.update_access_token(
                practice_id, new_ts.access_token, expires_at=new_expires_at
            )
        else:
            tokens.put(
                practice_id,
                access_token=new_ts.access_token,
                refresh_token=new_ts.refresh_token,
                expires_at=new_expires_at,
            )
        record = tokens.get(practice_id)
        return new_ts.access_token

    access_token = _do_refresh(force=False)
    return practice.fhir_base_url, access_token, RefreshContext(_do_refresh)
