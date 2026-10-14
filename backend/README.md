# Metriks AI — Backend

Python + FastAPI API for the Metriks AI document management system.

## Requirements

- Python 3.12 or newer (`.python-version` pins 3.12)
- [uv](https://docs.astral.sh/uv/) for dependency management (`pip install uv` or see the uv docs)

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

## Setup

```bash
cd backend
uv sync
```

## Run locally

```bash
uv run uvicorn app.main:app --reload --port 8000
```

| URL                                | Purpose                                      |
| ---------------------------------- | -------------------------------------------- |
| <http://localhost:8000/health>     | Liveness: the process is up                  |
| <http://localhost:8000/ready>      | Readiness: the app has started               |
| <http://localhost:8000/docs>       | Interactive OpenAPI documentation            |

`/ready` currently verifies nothing beyond application startup: there is no database, storage or external service integration yet, so `checks` is empty. Dependency checks will be added together with each integration.

## Configuration

Settings are read from environment variables, or from a local `.env` file in `backend/` (never commit it). See `app/core/config.py`.

| Variable    | Allowed values                                   | Default |
| ----------- | ------------------------------------------------ | ------- |
| `APP_ENV`   | `local`, `test`, `production`                    | `local` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`  | `INFO`  |

Invalid values stop the application at startup. Logs are written to stdout as single-line JSON.

All errors are returned as `{"error": {"code": "...", "message": "..."}}`.

## Tests and linting

Tests need no AWS credentials, database or API keys.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .   # use `uv run ruff format .` to apply
python -m compileall -q app tests
```

## Structure

```
app/
  main.py          application factory (create_app) and ASGI entry point
  api/health.py    /health and /ready routes
  core/config.py   settings
  core/logging.py  JSON logging
  core/errors.py   exception handlers
tests/
```
