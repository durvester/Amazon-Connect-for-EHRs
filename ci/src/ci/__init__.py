"""CI harness (Session 0005).

Four layers driven by `make test-ci`:
  1. unit             — pytest + vitest across all packages
  2. svc-integration  — pytest with moto + real PF QA refresh
  3. ui-e2e           — Playwright against local API+web stack
  4. agent-e2e        — Strands local-invoke against synthetic Connect events
"""

LAYER_MARKERS = ("unit", "svc-integration", "ui-e2e", "agent-e2e")
"""Tags the Makefile recipe prints (via `echo ::ci-layer::<name>`). The
self-check parses `make -n test-ci` output for these markers — adding a
layer means updating both this tuple and the Makefile."""
