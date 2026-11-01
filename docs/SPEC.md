# Haushaltsbuch – Specification

A deliberately simple, self-hosted income/expense tracker for one household. Mobile-first PWA, manual entry only, one Docker container.

**Guiding principle:** boring and fast beats clever. If a feature isn't in this document, don't build it. Ask first.

---

## 1. Goals

- Log an expense on a phone in under 5 seconds (amount → category → save).
- Track which account paid for something.
- Clear statistics: day / month / year, per category, with drill-down.
- Honest numbers for a bank loan application (Haushaltsrechnung): monthly averages per category over N months.
- Exportable statements (CSV, PDF).

## 2. Non-goals (do NOT implement)

- User accounts, login, roles, multi-user
- Budgets / envelope budgeting
- Double-entry bookkeeping
- Bank sync or bank file import
- Multiple currencies (EUR only)
- Stock prices / portfolio valuation
- Receipt scanning, OCR, AI features
- Offline entry queue (VPN is always available)
- Any external network calls at runtime (no CDNs, no telemetry)

## 3. Users & access

- Single household, no authentication. One main operator; others may view.
- Runs on the internal network only. Mobile access via WireGuard VPN.
- Reverse proxy (Caddy on OPNsense) restricts access to LAN + WireGuard subnets. The app itself has no auth.

## 4. Locale

- UI language: German.
- Number format: `1.234,56 €` (de-AT). Input accepts comma as the decimal separator.
- Date format: `dd.mm.yyyy`. Timezone: `Europe/Vienna`.
- Week starts Monday.

## 5. Data model

All amounts are stored as **integer cents**, always positive. The entry type determines direction.

### 5.1 Account
| Field | Type | Notes |
|---|---|---|
| id | int | |
| name | text | e.g. "Girokonto Alex", "Girokonto Partnerin", "Bargeld", "Depot" |
| owner | text, optional | free label, e.g. "Alex", "Partnerin", "Gemeinsam" |
| kind | enum | `checking`, `cash`, `savings` |
| archived | bool | hidden from pickers, kept in history |
| sort_order | int | |

`savings` accounts (Depot, Sparkonto) drive the "Gespart" figure (see 7.1).

### 5.2 Category (two levels)
| Field | Type | Notes |
|---|---|---|
| id | int | |
| name | text | |
| parent_id | int, nullable | null = main category; max depth 2 |
| type | enum | `income` or `expense`; subcategories inherit from parent |
| emoji | text | shown on quick-add tiles |
| color | text | hex, used in charts |
| archived | bool | |
| sort_order | int | |

Entries may reference a main category directly or a subcategory. Subcategories are optional.

### 5.3 Tag
| Field | Type | Notes |
|---|---|---|
| id | int | |
| name | text | e.g. "Kreditkarte", "Urlaub 2027" |

Entries ↔ tags is many-to-many.

### 5.4 Entry
| Field | Type | Notes |
|---|---|---|
| id | int | |
| type | enum | `income`, `expense`, `transfer` |
| date | date | defaults to today |
| amount_cents | int | > 0 |
| account_id | int | income: target account; expense: paying account; transfer: source |
| to_account_id | int, nullable | transfer only: target account |
| category_id | int, nullable | required for income/expense; must be null for transfer |
| note | text, optional | |
| recurring_id | int, nullable | set if created from a recurring template |
| created_at / updated_at | timestamp | |

Validation:
- Category type must match entry type.
- Transfer: `account_id != to_account_id`, no category.

### 5.5 Recurring template
| Field | Type | Notes |
|---|---|---|
| id | int | |
| name | text | e.g. "Miete", "ETF-Sparplan" |
| type, amount_cents, account_id, to_account_id, category_id, note, tags | | same rules as Entry |
| frequency | enum | `weekly`, `monthly`, `quarterly`, `yearly` |
| day | int | day of month (1–31; clamp to the last day of short months) or weekday for weekly |
| start_date | date | |
| end_date | date, nullable | |
| active | bool | |

### 5.6 Recurring occurrence (pending)
Generated for every due date up to today that has no booked entry yet.
| Field | Type | Notes |
|---|---|---|
| id | int | |
| recurring_id | int | |
| due_date | date | |
| status | enum | `pending`, `booked`, `skipped` |
| entry_id | int, nullable | set when booked |

Occurrences are **never auto-booked**. They appear as pending until the user confirms (optionally editing the amount/date first) or skips them. Generation is idempotent (unique on recurring_id + due_date).

## 6. Bookkeeping rules (document these in the UI help text too)

1. **Credit card:** card purchases are booked as expenses on the account that eventually gets charged (e.g. Girokonto Alex), optionally tagged "Kreditkarte". The monthly credit card settlement on the bank statement is **never** booked, since that would double-count.
2. **Cash:** ATM withdrawal = transfer Girokonto → Bargeld. Cash purchases = expenses from Bargeld.
3. **Stocks / savings plan:** buying = transfer Girokonto → Depot (a `savings` account). Selling = transfer Depot → Girokonto. Dividends = income (category "Kapitalerträge") into whichever account receives them. Depot fees = expense. No market values are tracked; the Depot balance means "net amount invested", not current worth.
4. **Money between partners:** transfer between their accounts. Never income/expense.

## 7. Statistics

### 7.1 Definitions
- **Einnahmen** = sum of income entries.
- **Ausgaben** = sum of expense entries.
- **Gespart** = transfers *into* `savings` accounts minus transfers *out of* `savings` accounts into non-savings accounts.
- **Saldo** = Einnahmen − Ausgaben − Gespart.
- Transfers between non-savings accounts are ignored in all statistics.
- Pending (unconfirmed) recurring occurrences are **not** included in statistics.

### 7.2 Views
- **Monat (default):** Einnahmen / Ausgaben / Gespart / Saldo at the top, with the delta vs. the previous month. Breakdown per main category (donut + sorted list with amounts and %). Tap a main category to drill into its subcategories and entries. Month switcher with swipe/arrows.
- **Jahr:** monthly bar chart (Einnahmen vs. Ausgaben, Gespart as a separate series), totals, and a category breakdown for the year.
- **Tag:** list of that day's entries with a daily total. No chart.
- **Filters** (all views): account(s), tag(s).
- **Kreditansicht (loan view):** select N months (default 6, complete months only). Table of the **monthly average** per main category (expandable to subcategories) for income, expenses and Gespart, plus totals. This is the input for a bank's Haushaltsrechnung.

Charts: Chart.js, vendored locally.

## 8. Screens

1. **Home / Quick add**
   - Pending recurring occurrences at the top (confirm ✓ / edit ✎ / skip ✕).
   - Segmented control: Ausgabe (default) / Einnahme / Umbuchung.
   - Large amount field (`inputmode="decimal"`), autofocused.
   - Category tile grid (emoji + name) for main categories; tapping a main category with subcategories shows them as a second row (also selectable: the main category itself).
   - Account picker remembers the last used account.
   - Date (default today), note, tags collapsed under "Mehr".
   - Save → toast with "Rückgängig" (undo) for 5 seconds.
2. **Buchungen (list):** grouped by day, infinite scroll, search in notes, same filters as stats. Tap to edit; delete with confirmation.
3. **Statistik:** Monat / Jahr / Tag / Kreditansicht tabs.
4. **Einstellungen:** manage accounts, categories (drag to reorder, archive instead of delete when used), tags, and recurring templates. Export and backup status live here too.

Navigation: bottom tab bar (Erfassen, Buchungen, Statistik, Einstellungen).

## 9. Exports

- **CSV:** all entries in a date range, semicolon-separated, UTF-8 with BOM (Excel-friendly in de-AT). Columns: Datum, Typ, Betrag, Konto, Zielkonto, Hauptkategorie, Unterkategorie, Tags, Notiz.
- **PDF statement:** per month or year. Summary figures, category breakdown table, entry list. Also a PDF of the Kreditansicht. Generated server-side (WeasyPrint).

## 10. Seed data (editable after first start)

Accounts: Girokonto Alex, Girokonto Partnerin, Bargeld, Depot (`savings`).
Tags: Kreditkarte.
Categories (suggestion, keep short):
- Einnahmen: Gehalt, Kapitalerträge, Sonstiges
- Wohnen: Miete, Betriebskosten, Strom, Internet/Handy
- Lebensmittel: Supermarkt, Markt/Bäcker
- Mobilität: Öffis, Tanken, Auto
- Versicherungen
- Kind: Schule, Freizeit, Kleidung
- Gesundheit
- Freizeit: Essen gehen, Hobbys, Urlaub
- Abos
- Haushalt & Kleidung
- Gebühren (incl. Depotgebühren)
- Sonstiges

## 11. Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic migrations, SQLite in WAL mode.
- **Frontend:** server-rendered Jinja2 + HTMX, minimal hand-written CSS (mobile-first, dark mode via `prefers-color-scheme`). No JS build step. Chart.js and HTMX vendored into `/static`.
- **PWA:** web manifest, icons, and a service worker that caches only the app shell/static assets (no offline writes).
- **PDF:** WeasyPrint.
- **Tests:** pytest. Cover the statistics definitions (7.1), transfer validation, recurring occurrence generation (month-end clamping, idempotency), and CSV export.

## 12. Deployment

- Single container, runs as non-root, listens on port 8080.
- `/health` endpoint for the Docker healthcheck.
- Data volume mounted at `/data` inside the container (database at `/data/haushaltsbuch.db`, backups at `/data/backups/`).
- Host path (Unraid): `/mnt/user/appdata/haushaltsbuch` → `/data`.
- Ship `Dockerfile`, `docker-compose.yml` and a `README.md` with setup steps. Use absolute paths everywhere in docs and compose.

Example `docker-compose.yml`:

```yaml
services:
  haushaltsbuch:
    build: .
    container_name: haushaltsbuch
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=Europe/Vienna
      - BACKUP_KEEP_DAYS=14
    volumes:
      - /mnt/user/appdata/haushaltsbuch:/data
```

### Backup
- Nightly (03:00 Europe/Vienna) the app writes a consistent copy via SQLite's online backup API to `/data/backups/haushaltsbuch-YYYY-MM-DD.db`, keeping the last 14 days (configurable).
- Restic/Backrest on the host backs up `/mnt/user/appdata/haushaltsbuch/backups/`, never the live DB file.
- Settings page shows the time of the last successful backup.

### Repository hygiene (financial data)
- The repository must never contain real financial data: no IBANs/account or card numbers, real amounts or statements, databases, backups, CSV/PDF exports, or `.env` files.
- Seed data, tests and fixtures use made-up amounts only.
- Enforced by `.gitignore` and the hooks in `.githooks/` (see README).

## 13. Milestones

1. **M1 – Core:** data model + migrations, seed data, quick add, entry list, edit/delete, settings for accounts/categories/tags.
2. **M2 – Recurring:** templates, occurrence generation, confirm/edit/skip on home.
3. **M3 – Statistics:** month/year/day views, filters, drill-down.
4. **M4 – Exports & loan view:** CSV, PDF statements, Kreditansicht.
5. **M5 – PWA & ops:** manifest, service worker, backup job, healthcheck, README.

Each milestone ends with passing tests and a working `docker compose up`.

## 14. Acceptance criteria (spot checks)

- Logging an expense on a phone takes ≤ 3 taps after typing the amount.
- An ATM withdrawal (transfer to Bargeld) does not change Ausgaben.
- A €200 Sparplan transfer to Depot raises Gespart by €200 and leaves Ausgaben unchanged.
- A recurring template for the 31st generates a pending occurrence on 28/29 Feb and 30 Apr.
- Restarting the app does not duplicate pending occurrences.
- The CSV opens correctly in Excel (de-AT) with umlauts intact.
- The app makes zero outbound network requests (verify in browser dev tools).
