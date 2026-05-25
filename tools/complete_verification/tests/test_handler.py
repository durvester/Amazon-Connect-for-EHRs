"""Tests for complete_verification handler. Real coverage in Session 0004."""

import pytest


def test_handler_not_implemented():
    from complete_verification.handler import handler

    with pytest.raises(NotImplementedError):
        handler({}, None)
