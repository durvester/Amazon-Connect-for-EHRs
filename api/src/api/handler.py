"""AWS Lambda entrypoint (Mangum adapter).

The Lambda runtime hands API Gateway / Function URL events to
``handler``; Mangum translates them into ASGI requests for the
FastAPI app built by ``build_app()``.

``build_app`` constructs production deps from env vars on first call;
subsequent warm invocations reuse the same app instance.
"""

from __future__ import annotations

from mangum import Mangum

from api.app import build_app

_app = build_app()
handler = Mangum(_app, lifespan="off")
