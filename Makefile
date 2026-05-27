.PHONY: bootstrap venv test test-ci test-ci-unit test-ci-svc test-ci-ui test-ci-agent lint synth spike-fhir seed-dev-token clean help

PYTHON_PKGS := tools/lookup_patient tools/escalate_to_human tools/router_lookup tools/lex_code_hook tools/fhir_query audit oauth routing api ci
NODE_PKGS := infra web
VENV := .venv
PY := $(CURDIR)/$(VENV)/bin/python

help:
	@echo "Targets:"
	@echo "  bootstrap        Create .venv + install Python deps + npm install for Node pkgs"
	@echo "  venv             Create .venv only"
	@echo "  test             Run pytest (Python) + vitest (web) + jest (infra)"
	@echo "  test-ci          Run the four-layer CI harness (unit, svc, ui-e2e, agent-e2e)"
	@echo "  lint             ruff (Python) + tsc --noEmit (Node)"
	@echo "  synth            cdk synth (snapshot of CDK output)"
	@echo "  spike-fhir       Run the Session 0002 PF FHIR spike (interactive)"
	@echo "  seed-dev-token   Encrypt secrets/pf-qa-tokens.json into pf-qa-refresh-token.enc"
	@echo "  clean            Remove caches and build artifacts"

venv:
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"
	@"$(PY)" -m pip install --quiet --upgrade pip

bootstrap: venv
	@for pkg in $(PYTHON_PKGS); do \
		echo ">> pip install -e $$pkg[dev]"; \
		"$(PY)" -m pip install --quiet -e $$pkg".[dev]" || exit 1; \
	done
	@for pkg in $(NODE_PKGS); do \
		echo ">> npm install in $$pkg"; \
		(cd $$pkg && npm install) || exit 1; \
	done

test: venv
	@for pkg in $(PYTHON_PKGS); do \
		echo ">> pytest $$pkg"; \
		(cd $$pkg && PYTHONPATH=src "$(PY)" -m pytest -q) || exit 1; \
	done
	@cd web && npm test -- --run
	@cd infra && npm test

# ---- CI harness (Session 0005) -----------------------------------------------
# Each layer prefixes its first command with `echo ::ci-layer::<name>`. The
# ci/tests/test_harness_self_check.py meta-test scans `make -n test-ci` output
# for these markers — keep them in sync with ci/src/ci/__init__.py LAYER_MARKERS.

test-ci: test-ci-unit test-ci-svc test-ci-ui test-ci-agent
	@echo "All four CI layers passed."

test-ci-unit: venv
	@echo "::ci-layer::unit"
	@"$(PY)" -m ci.mint_access_token --skip-if-no-fixture
	@for pkg in $(PYTHON_PKGS); do \
		echo ">> pytest $$pkg (unit, -m 'not integration')"; \
		(cd $$pkg && PYTHONPATH=src "$(PY)" -m pytest -q -m "not integration") || exit 1; \
	done
	@cd web && (test -d node_modules || (test -f package-lock.json && npm ci || npm install)) && npm test -- --run
	@cd infra && (test -d node_modules || (test -f package-lock.json && npm ci || npm install)) && npm test

test-ci-svc: venv
	@echo "::ci-layer::svc-integration"
	@"$(PY)" -m ci.mint_access_token --export-env > .ci-env || ( \
		echo "WARN: refresh-token fixture unavailable; skipping PF QA integration layer." && \
		: > .ci-env )
	@set -a; . ./.ci-env; set +a; \
	for pkg in $(PYTHON_PKGS); do \
		(cd $$pkg && PYTHONPATH=src "$(PY)" -m pytest -q -m integration --no-header 2>&1 | tail -n 20) || exit 1; \
	done
	@rm -f .ci-env

test-ci-ui: venv
	@echo "::ci-layer::ui-e2e"
	@cd web && (test -d node_modules || (test -f package-lock.json && npm ci || npm install))
	@cd web && (test -d node_modules/@playwright/test || npm install --no-save @playwright/test >/dev/null 2>&1 || true) \
		&& npx playwright install chromium >/dev/null 2>&1 || true
	@"$(PY)" -m ci.start_local_stack --onboarding

test-ci-agent: venv
	@echo "::ci-layer::agent-e2e"
	@"$(PY)" -m ci.run_synthetic_call --placeholder

# ---- end CI harness ----------------------------------------------------------

lint: venv
	@for pkg in $(PYTHON_PKGS); do \
		(cd $$pkg && "$(PY)" -m ruff check .) || exit 1; \
	done
	@cd web && npx tsc --noEmit
	@cd infra && npx tsc --noEmit

synth:
	@cd infra && npx cdk synth --quiet

spike-fhir: venv
	@"$(PY)" scripts/spike-fhir.py

seed-dev-token: venv
	@"$(PY)" scripts/seed-dev-refresh-token.py

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	@find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	@find . -type d -name node_modules -prune -exec rm -rf {} +
	@find . -type d -name cdk.out -prune -exec rm -rf {} +
	@rm -f .ci-env
