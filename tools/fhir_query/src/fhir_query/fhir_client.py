"""Generalized FHIR search client for clinical resource queries.

One-shot 401 refresh-and-retry, same pattern as lookup_patient's client.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import requests

_TIMEOUT_SECONDS = 10.0

RefreshAccessToken = Callable[[], str]


class FhirQueryError(RuntimeError):
    pass


def search_resources(
    resource_type: str,
    params: dict[str, str],
    base_url: str,
    access_token: str,
    *,
    refresh_access_token: Optional[RefreshAccessToken] = None,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + f"/{resource_type}"
    token = access_token

    resp = _get(url, params, token)

    if resp.status_code == 401 and refresh_access_token is not None:
        token = refresh_access_token()
        resp = _get(url, params, token)

    if not resp.ok:
        raise FhirQueryError(
            f"FHIR {resource_type} search failed: {resp.status_code} {resp.text[:200]}"
        )

    bundle = resp.json()
    return [
        entry["resource"]
        for entry in bundle.get("entry", [])
        if entry.get("resource", {}).get("resourceType") == resource_type
    ]


def _get(url: str, params: dict[str, str], token: str) -> requests.Response:
    return requests.get(
        url,
        params=params,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        timeout=_TIMEOUT_SECONDS,
    )
