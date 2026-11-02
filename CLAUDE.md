# Haushaltsbuch

Specification: `docs/SPEC.md`. If a feature isn't in the spec, don't build it – ask first.

## Financial data – hard rule

No real financial data may ever be committed: no IBANs or account/card numbers, real amounts or statements, databases, backups, exports or `.env` files. Seed data, tests and fixtures use made-up amounts only. Never bypass the hooks (`--no-verify`), and never edit `.gitignore` / `.githooks/` / `scripts/check-personal-data.sh` to make a blocked commit pass – fix the content instead.

## Dev

- Tests: `.venv/bin/pytest` (container runs Python 3.12; local venv may be newer – both must pass).
  In the built image (3.12 + WeasyPrint libs): `docker compose build`, then
  `docker run --rm --user root -e DATA_DIR=/tmp/d -v "$PWD/tests":/app/tests:ro,Z -v "$PWD/pytest.ini":/app/pytest.ini:ro,Z haushaltsbuch-haushaltsbuch sh -c "pip install -q pytest httpx && pytest -p no:cacheprovider"`.
- Tests disable the backup scheduler (`BACKUP_ENABLED=false` in `tests/conftest.py`).
- PDFs (WeasyPrint) must stay self-contained: `app/pdf.py` blocks every external URL; no emoji in PDF templates (no emoji font in the image).
- Local run: `DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8080` (`data/` is gitignored).
- Migrations run on app start (`app/db.py:migrate`). Seed data is migration `0002` and runs once – don't re-seed elsewhere.
- No outbound network calls at runtime: vendor JS into `app/static/vendor/`, reference assets via `{{ static('…') }}` (cache-busting).
