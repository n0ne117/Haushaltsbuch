# Haushaltsbuch

A deliberately simple, self-hosted income/expense tracker for one household. Mobile-first PWA, manual entry only, one Docker container.

See [docs/SPEC.md](docs/SPEC.md) for the full specification. Setup instructions follow with milestone M5.

## Privacy – no financial data in this repository

Real financial data (IBANs, account/card numbers, real amounts, the database, backups, CSV/PDF exports, `.env`) must never be committed.

Safeguards:

1. **`.gitignore`** excludes databases, backups, `data/`, exports (`*.csv`, `*.pdf`, …) and `.env*`.
2. **Git hooks** in `.githooks/` run `scripts/check-personal-data.sh`:
   - `pre-commit` checks the staged changes,
   - `pre-push` re-checks every commit being pushed (also catches `git commit --no-verify`).

   They block forbidden file types, IBAN-like strings, and strings from your local `.personal-patterns` blocklist.

After every fresh clone, enable the hooks:

```bash
git config core.hooksPath .githooks
```

Optionally create `.personal-patterns` (gitignored) with one string per line – account, card or depot numbers etc. that the IBAN check wouldn't catch. Matching is case-sensitive and whole-word.

Test fixtures that need CSV files go in `tests/fixtures/` and must use made-up data only.
