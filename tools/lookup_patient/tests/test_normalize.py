"""Tests for phone normalization helpers."""

import pytest

from lookup_patient.normalize import (
    PhoneFormatError,
    normalize_e164,
    to_pf_phone_formats,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("5551234567", "+15551234567"),
        ("(555) 123-4567", "+15551234567"),
        ("555-123-4567", "+15551234567"),
        ("555.123.4567", "+15551234567"),
        ("+15551234567", "+15551234567"),
        ("+1 (555) 123-4567", "+15551234567"),
        ("1-555-123-4567", "+15551234567"),
        ("15551234567", "+15551234567"),
    ],
)
def test_normalizes_common_us_formats(raw, expected):
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "12345",            # too short
        "555123456",        # 9 digits
        "+445551234567",    # 12 digits starting with non-US
    ],
)
def test_rejects_invalid_inputs(raw):
    with pytest.raises(PhoneFormatError):
        normalize_e164(raw)


def test_rejects_non_us_default_country():
    with pytest.raises(NotImplementedError):
        normalize_e164("5551234567", default_country="GB")


# --- to_pf_phone_formats (ADR-0006) ---

@pytest.mark.parametrize(
    "raw",
    [
        "7163619276",
        "716-361-9276",
        "(716) 361-9276",
        "716.361.9276",
        "+17163619276",
        "1-716-361-9276",
        "716 361 9276",
    ],
)
def test_pf_formats_first_is_paren_space(raw):
    formats = to_pf_phone_formats(raw)
    # ADR-0006: PF's apparent storage default is "(NPA) NXX-XXXX" — try first.
    assert formats[0] == "(716) 361-9276"


def test_pf_formats_returns_priority_ordered_list():
    formats = to_pf_phone_formats("7163619276")
    assert formats == [
        "(716) 361-9276",
        "+1(716)361-9276",
        "716-361-9276",
        "716.361.9276",
        "(716)361-9276",
        "+17163619276",
        "716 361 9276",
        "7163619276",
    ]


def test_pf_formats_deduplicates_preserving_order():
    # If a future caller adds a duplicate format, output must still be unique.
    formats = to_pf_phone_formats("(716) 361-9276")
    assert len(formats) == len(set(formats))


@pytest.mark.parametrize("raw", ["", "abc", "12345", "555123456"])
def test_pf_formats_rejects_invalid(raw):
    with pytest.raises(PhoneFormatError):
        to_pf_phone_formats(raw)
