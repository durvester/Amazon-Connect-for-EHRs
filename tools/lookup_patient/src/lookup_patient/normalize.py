"""Input normalization for patient lookups.

Two helpers live here:

- `normalize_e164` — produces canonical `+1XXXXXXXXXX`. Used for audit-log
  redaction and any non-FHIR code path that wants a single canonical phone.

- `to_pf_phone_formats` — produces the priority-ordered list of probe formats
  for Practice Fusion's `Patient?telecom=` search. PF does literal string
  matching, so the query format must equal the stored format (ADR-0006).
"""

from __future__ import annotations

import re

_US_DIGITS = re.compile(r"\D")


class PhoneFormatError(ValueError):
    """Raised when an input phone cannot be normalized."""


def _to_10_digits(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        raise PhoneFormatError(f"empty or non-string input: {raw!r}")
    digits = _US_DIGITS.sub("", raw[1:] if raw.startswith("+") else raw)
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    if len(digits) == 10:
        return digits
    raise PhoneFormatError(
        f"expected 10 or 11 US digits, got {len(digits)} from {raw!r}"
    )


def normalize_e164(raw: str, *, default_country: str = "US") -> str:
    """Normalize a US phone number to E.164 (`+1XXXXXXXXXX`)."""
    if default_country != "US":
        raise NotImplementedError("Only US numbers in v1")
    return "+1" + _to_10_digits(raw)


def to_pf_phone_formats(raw: str) -> list[str]:
    """Return PF FHIR probe formats in priority order (ADR-0006).

    The list is deduplicated while preserving order. The first format is the
    one PF's UI appears to write by default; if it misses, fall through the
    remaining variants to handle practices with non-default data entry.
    """
    d = _to_10_digits(raw)
    npa, nxx, line = d[0:3], d[3:6], d[6:10]
    ordered = [
        f"({npa}) {nxx}-{line}",    # PF default storage
        f"+1({npa}){nxx}-{line}",   # PF alternate with country code
        f"{npa}-{nxx}-{line}",
        f"{npa}.{nxx}.{line}",
        f"({npa}){nxx}-{line}",
        f"+1{d}",                    # E.164
        f"{npa} {nxx} {line}",
        d,                           # digits only
    ]
    seen: set[str] = set()
    out: list[str] = []
    for f in ordered:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out
