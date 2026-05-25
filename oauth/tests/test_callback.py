"""OAuth callback route tests. Real coverage in Session 0006."""

import pytest


def test_routes_not_implemented():
    from oauth.routes import build_app

    with pytest.raises(NotImplementedError):
        build_app()
