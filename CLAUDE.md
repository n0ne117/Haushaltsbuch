# Haushaltsbuch

Specification: `docs/SPEC.md`. If a feature isn't in the spec, don't build it – ask first.

## Financial data – hard rule

No real financial data may ever be committed: no IBANs or account/card numbers, real amounts or statements, databases, backups, exports or `.env` files. Seed data, tests and fixtures use made-up amounts only. Never bypass the hooks (`--no-verify`), and never edit `.gitignore` / `.githooks/` / `scripts/check-personal-data.sh` to make a blocked commit pass – fix the content instead.

## Dev

- Tests: `.venv/bin/pytest` (container runs Python 3.12; local venv may be newer – both must pass).
- Local run: `DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8080` (`data/` is gitignored).
- Migrations run on app start (`app/db.py:migrate`). Seed data is migration `0002` and runs once – don't re-seed elsewhere.
- No outbound network calls at runtime: vendor JS into `app/static/vendor/`, reference assets via `{{ static('…') }}` (cache-busting).
