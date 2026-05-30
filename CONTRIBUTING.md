# Contributing

## Prerequisites

- Python 3.12
- Node 22
- AWS CLI v2 (SSO-authenticated to your AWS account)
- AWS CDK v2 (`npm i -g aws-cdk`)

## Setup

```bash
make bootstrap   # creates .venv, installs all Python + Node deps
```

## Development workflow

```bash
make test        # pytest (all Python packages) + jest (infra CDK tests)
make lint        # ruff (Python) + tsc --noEmit (TypeScript)
make synth       # CDK synth — generates CloudFormation templates
```

Run a single Python package's tests:

```bash
cd tools/lookup_patient && PYTHONPATH=src .venv/bin/python -m pytest -q
```

Skip integration tests (no AWS credentials needed):

```bash
cd tools/lookup_patient && PYTHONPATH=src .venv/bin/python -m pytest -q -m "not integration"
```

## Project structure

All Python packages follow the same layout: `<pkg>/src/<module>/`, `<pkg>/tests/`, `<pkg>/pyproject.toml`. Editable installs via `pip install -e .[dev]`. Tests require `PYTHONPATH=src` when run from a package directory.

## Conventions

- **TDD.** Write the failing test first, then implement.
- **No PHI in logs.** Log `practice_id`, `call_id`, decisions — never patient data values.
- **Secrets via Secrets Manager only.** No secrets in env vars at rest or committed to source.
- **IaC for everything.** The CDK app in `infra/` is the source of truth.
- **HIPAA-eligible services only.** Confirm eligibility before introducing a new AWS service.
- **ADR before architectural changes.** Write `docs/decisions/NNNN-<slug>.md` before changing the design.

## Code style

- Python: Ruff, line-length 100, target Python 3.12
- TypeScript: strict mode, no implicit any

## Submitting changes

1. Fork the repo and create a feature branch
2. Write tests first, then implement
3. Ensure `make test` and `make lint` pass
4. Open a pull request with a clear description of what and why
