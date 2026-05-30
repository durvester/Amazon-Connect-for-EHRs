.PHONY: bootstrap venv test lint synth clean help

PYTHON_PKGS := tools/lookup_patient tools/router_lookup tools/lex_code_hook tools/fhir_query audit oauth routing api
NODE_PKGS := infra
VENV := .venv
PY := $(CURDIR)/$(VENV)/bin/python

help:
	@echo "Targets:"
	@echo "  bootstrap        Create .venv + install Python deps + npm install for Node pkgs"
	@echo "  venv             Create .venv only"
	@echo "  test             Run pytest (Python) + jest (infra)"
	@echo "  lint             ruff (Python) + tsc --noEmit (Node)"
	@echo "  synth            cdk synth (snapshot of CDK output)"
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
	@cd infra && npm test

lint: venv
	@for pkg in $(PYTHON_PKGS); do \
		(cd $$pkg && "$(PY)" -m ruff check .) || exit 1; \
	done
	@cd infra && npx tsc --noEmit

synth:
	@cd infra && npx cdk synth --quiet

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	@find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	@find . -type d -name node_modules -prune -exec rm -rf {} +
	@find . -type d -name cdk.out -prune -exec rm -rf {} +
