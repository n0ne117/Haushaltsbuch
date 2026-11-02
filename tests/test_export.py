import csv
import io
import sqlite3
from datetime import date, datetime

import pytest

from app import fmt, pdf
from app.config import TZ
from app.services import backup, stats
from app.models import EntryType
from app.services.entries import EntryData, create_entry
from app.services.filters import EntryFilters


@pytest.fixture
def book(db, seed):
    def _book(type, cents, account, category=None, to=None, on=date(2026, 10, 10), note=None, tags=()):
        return create_entry(db, EntryData(
            EntryType(type), on, cents, seed.account(account).id,
            to_account_id=seed.account(to).id if to else None,
            category_id=seed.category(category).id if category else None,
            note=note, tag_ids=[seed.tag(t).id for t in tags],
        ))
    return _book


# --- CSV --------------------------------------------------------------------------------


def test_csv_export(client, book):
    book("expense", 123456, "Bargeld", "Markt/Bäcker", note="Grüße; \"Zitat\"", tags=["Kreditkarte"])
    book("transfer", 20000, "Girokonto Alex", to="Depot", on=date(2026, 10, 1))
    book("income", 100, "Girokonto Alex", "Gehalt", on=date(2026, 12, 1))  # outside range
    r = client.get("/export/entries.csv?from=2026-10-01&to=2026-10-31")
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="haushaltsbuch_2026-10-01_2026-10-31.csv"' in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    text = r.content.decode("utf-8-sig")
    assert "\r\n" in text
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0] == ["Datum", "Typ", "Betrag", "Konto", "Zielkonto", "Hauptkategorie", "Unterkategorie", "Tags", "Notiz"]
    assert rows[1] == ["01.10.2026", "Umbuchung", "200,00", "Girokonto Alex", "Depot", "", "", "", ""]
    assert rows[2] == ["10.10.2026", "Ausgabe", "1234,56", "Bargeld", "", "Lebensmittel", "Markt/Bäcker",
                       "Kreditkarte", 'Grüße; "Zitat"']
    assert len(rows) == 3


def test_csv_main_category_without_sub(client, book):
    book("expense", 500, "Bargeld", "Abos")
    rows = list(csv.reader(io.StringIO(client.get("/export/entries.csv?from=2026-01-01&to=2026-12-31")
                                       .content.decode("utf-8-sig")), delimiter=";"))
    assert rows[1][5:7] == ["Abos", ""]


# --- Kreditansicht ------------------------------------------------------------------------


def test_loan_period_complete_months_only():
    assert stats.loan_period(date(2026, 11, 2), 6) == (date(2026, 5, 1), date(2026, 11, 1))
    assert stats.loan_period(date(2026, 1, 31), 3) == (date(2025, 10, 1), date(2026, 1, 1))


def test_per_month_rounds_half_up():
    assert fmt.per_month(100, 6) == 17
    assert fmt.per_month(9, 6) == 2  # 1.5 → 2
    assert fmt.per_month(-9, 6) == -2


def test_statement_gespart_by_account(db, seed, book):
    from app.models import Account, AccountKind
    db.add(Account(name="Sparkonto", kind=AccountKind.savings))
    db.commit()
    book("transfer", 20000, "Girokonto Alex", to="Depot")
    book("transfer", 5000, "Depot", to="Girokonto Alex")
    book("transfer", 3000, "Girokonto Partnerin", to="Sparkonto")
    book("transfer", 1000, "Depot", to="Sparkonto")  # savings ↔ savings: ignored
    st = stats.statement(db, date(2026, 10, 1), date(2026, 11, 1), EntryFilters())
    assert {a.name: c for a, c in st.gespart} == {"Depot": 15000, "Sparkonto": 3000}
    assert st.totals.gespart == 18000


def test_loan_view(client, book):
    today = fmt.today()
    start, _ = stats.loan_period(today, 6)
    for i in range(6):
        y, m = stats.shift_month(start.year, start.month, i)
        book("income", 300000, "Girokonto Alex", "Gehalt", on=date(y, m, 1))
        book("expense", 90000 + i * 100, "Girokonto Alex", "Miete", on=date(y, m, 3))
        book("expense", 4000, "Bargeld", "Wohnen", on=date(y, m, 4))  # booked on the main category
    book("expense", 999999, "Bargeld", "Supermarkt", on=today)  # current month: excluded
    html = client.get("/stats/loan").text
    assert "Kreditansicht" in html and "Letzte 6 vollständige Monate" in html
    assert "3.000,00" in html                     # Ø Gehalt
    assert "942,50" in html                       # Ø Wohnen = (6×900 + 15 + 6×40) / 6
    assert "Ohne Unterkategorie" in html
    assert "9.999,99" not in html
    assert client.get("/stats/loan?n=12").status_code == 200


# --- PDF ----------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["/export/month.pdf?m=2026-10", "/export/year.pdf?y=2026", "/export/loan.pdf?n=6"])
def test_pdfs(client, book, url):
    book("expense", 2340, "Bargeld", "Supermarkt", note="Grüße")
    book("transfer", 20000, "Girokonto Alex", to="Depot")
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 2000
    assert r.headers["content-disposition"].startswith("inline")


def test_pdf_templates_render_content(db, book):
    book("expense", 2340, "Bargeld", "Supermarkt", note="Wocheneinkauf")
    st = stats.statement(db, date(2026, 10, 1), date(2026, 11, 1), EntryFilters())
    from app.templating import templates
    html = templates.get_template("pdf/statement.html").render(
        title="Monatsauszug Oktober 2026", filter_note="", statement=st, months=None, last_day=date(2026, 10, 31),
        entries=stats.entries(db, date(2026, 10, 1), date(2026, 11, 1), EntryFilters()), generated=datetime.now(TZ))
    for text in ["Monatsauszug Oktober 2026", "01.10.2026 – 31.10.2026", "Lebensmittel", "Supermarkt",
                 "Wocheneinkauf", "−23,40"]:
        assert text in html


def test_pdf_never_fetches_external_resources():
    with pytest.raises(ValueError):
        pdf._no_fetch("https://example.com/x.png")


def test_export_page(client):
    html = client.get("/settings/export").text
    assert "CSV herunterladen" in html and "Noch kein Backup" in html


# --- Backup ---------------------------------------------------------------------------------


def test_backup_writes_consistent_copy_and_prunes(client, db, book, tmp_path, monkeypatch):
    book("expense", 777, "Bargeld", "Supermarkt")
    monkeypatch.setenv("BACKUP_KEEP_DAYS", "3")
    for day in range(1, 6):
        backup.run_backup(date(2026, 10, day))
    names = [p.name for p in backup.backups()]
    assert names == ["haushaltsbuch-2026-10-05.db", "haushaltsbuch-2026-10-04.db", "haushaltsbuch-2026-10-03.db"]
    with sqlite3.connect(backup.backups()[0]) as conn:
        assert conn.execute("SELECT amount_cents FROM entries").fetchall() == [(777,)]
    assert not list(backup.backup_dir().glob("*.tmp"))
    status = backup.status()
    assert status["count"] == 3 and status["last_file"] == "haushaltsbuch-2026-10-05.db"
    assert "Letztes Backup" in client.get("/settings/export").text


def test_backup_catch_up(client, tmp_path):
    assert backup.needs_catch_up(date(2026, 10, 5))
    backup.run_backup(date(2026, 10, 4))
    assert not backup.needs_catch_up(date(2026, 10, 5))  # yesterday's run exists
    assert backup.needs_catch_up(date(2026, 10, 6))      # missed a night


def test_next_run_time_handles_dst():
    before = datetime(2026, 10, 24, 12, 0, tzinfo=TZ)  # DST ends on 25 Oct (25 h day)
    assert backup.seconds_until_next_run(before) == (15 + 1) * 3600
    at_night = datetime(2026, 11, 2, 2, 30, tzinfo=TZ)
    assert backup.seconds_until_next_run(at_night) == 30 * 60
