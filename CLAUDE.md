# Haushaltsbuch

Specification: `docs/SPEC.md`. If a feature isn't in the spec, don't build it – ask first.

## Financial data – hard rule

No real financial data may ever be committed: no IBANs or account/card numbers, real amounts or statements, databases, backups, exports or `.env` files. Seed data, tests and fixtures use made-up amounts only. Never bypass the hooks (`--no-verify`), and never edit `.gitignore` / `.githooks/` / `scripts/check-personal-data.sh` to make a blocked commit pass – fix the content instead.
