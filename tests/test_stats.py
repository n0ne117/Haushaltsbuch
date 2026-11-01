from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    Account,
    AccountKind,
    CategoryType,
    EntryType,
    Frequency,
    RecurringOccurrence,
    RecurringTemplate,
)
from app.services import recurring, stats
from app.services.entries import EntryData, create_entry
from app.services.filters import EntryFilters

NOV = stats.month_range(2026, 11)
NONE = EntryFilters()
D = date(2026, 11, 10)


@pytest.fixture
def book(db, seed):
    def _book(type, cents, account, category=None, to=None, on=D, tags=()):
        return create_entry(db, EntryData(
            EntryType(type), on, cents, seed.account(account).id,
            to_account_id=seed.account(to).id if to else None,
            category_id=seed.category(category).id if category else None,
            tag_ids=[seed.tag(t).id for t in tags],
        ))
    return _book


def test_income_and_expense(db, book):
    book("income", 300000, "Girokonto Alex", "Gehalt")
    book("expense", 2340, "Bargeld", "Supermarkt")
    book("expense", 95000, "Girokonto Alex", "Miete")
    t = stats.totals(db, *NOV, NONE)
    assert (t.einnahmen, t.ausgaben, t.gespart, t.saldo) == (300000, 97340, 0, 202660)


def test_atm_withdrawal_changes_nothing(db, book):
    book("transfer", 10000, "Girokonto Alex", to="Bargeld")
    assert stats.totals(db, *NOV, NONE) == stats.Totals(0, 0, 0)


def test_savings_plan_counts_as_gespart(db, book):
    book("transfer", 20000, "Girokonto Alex", to="Depot")
    t = stats.totals(db, *NOV, NONE)
    assert (t.ausgaben, t.gespart, t.saldo) == (0, 20000, -20000)


def test_selling_from_depot_reduces_gespart(db, book):
    book("transfer", 20000, "Girokonto Alex", to="Depot")
    book("transfer", 5000, "Depot", to="Girokonto Partnerin")
    assert stats.totals(db, *NOV, NONE).gespart == 15000


def test_transfer_between_savings_accounts_ignored(db, seed, book):
    db.add(Account(name="Sparkonto", kind=AccountKind.savings))
    db.commit()
    book("transfer", 7000, "Depot", to="Sparkonto")
    assert stats.totals(db, *NOV, NONE).gespart == 0


def test_dividends_are_income_and_fees_expense(db, book):
    book("income", 1234, "Girokonto Alex", "Kapitalerträge")
    book("expense", 300, "Girokonto Alex", "Gebühren")
    t = stats.totals(db, *NOV, NONE)
    assert (t.einnahmen, t.ausgaben) == (1234, 300)


def test_period_bounds(db, book):
    book("expense", 100, "Bargeld", "Supermarkt", on=date(2026, 10, 31))
    book("expense", 200, "Bargeld", "Supermarkt", on=date(2026, 11, 1))
    book("expense", 400, "Bargeld", "Supermarkt", on=date(2026, 11, 30))
    book("expense", 800, "Bargeld", "Supermarkt", on=date(2026, 12, 1))
    assert stats.totals(db, *NOV, NONE).ausgaben == 600
    months = stats.monthly_totals(db, 2026, NONE)
    assert [m.ausgaben for m in months[9:]] == [100, 600, 800]


def test_pending_occurrences_not_counted(db, seed):
    t = RecurringTemplate(name="Miete", type=EntryType.expense, amount_cents=95000,
                          account_id=seed.account("Girokonto Alex").id, category_id=seed.category("Miete").id,
                          frequency=Frequency.monthly, day=1, start_date=date(2026, 11, 1), active=True)
    db.add(t)
    db.commit()
    recurring.generate(db, date(2026, 11, 30))
    assert db.scalars(select(RecurringOccurrence)).one()
    assert stats.totals(db, *NOV, NONE).ausgaben == 0


def test_filters(db, seed, book):
    book("expense", 1000, "Bargeld", "Supermarkt", tags=["Kreditkarte"])
    book("expense", 2000, "Girokonto Alex", "Supermarkt")
    book("transfer", 20000, "Girokonto Alex", to="Depot")
    bargeld = EntryFilters(account_ids=[seed.account("Bargeld").id])
    assert stats.totals(db, *NOV, bargeld) == stats.Totals(0, 1000, 0)
    alex = EntryFilters(account_ids=[seed.account("Girokonto Alex").id])
    assert stats.totals(db, *NOV, alex) == stats.Totals(0, 2000, 20000)
    kk = EntryFilters(tag_ids=[seed.tag("Kreditkarte").id])
    assert stats.totals(db, *NOV, kk).ausgaben == 1000


def test_breakdown_and_drilldown(db, seed, book):
    book("expense", 6000, "Bargeld", "Supermarkt")
    book("expense", 2000, "Bargeld", "Markt/Bäcker")
    book("expense", 1000, "Bargeld", "Lebensmittel")  # booked on the main category itself
    book("expense", 10000, "Girokonto Alex", "Miete")
    shares = stats.by_main_category(db, *NOV, NONE, CategoryType.expense)
    assert [(s.category.name, s.cents) for s in shares] == [("Wohnen", 10000), ("Lebensmittel", 9000)]
    assert round(sum(s.pct for s in shares)) == 100
    subs = stats.by_subcategory(db, seed.category("Lebensmittel"), *NOV, NONE)
    assert [(s.category.name, s.cents) for s in subs] == [
        ("Supermarkt", 6000), ("Markt/Bäcker", 2000), ("Lebensmittel", 1000)]


def test_shift_month():
    assert stats.shift_month(2026, 1, -1) == (2025, 12)
    assert stats.shift_month(2026, 12, 1) == (2027, 1)
    assert stats.month_range(2026, 12) == (date(2026, 12, 1), date(2027, 1, 1))


# --- Web -------------------------------------------------------------------------------


def test_stats_redirects_to_month(client):
    r = client.get("/stats", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/stats/month"


def test_month_view(client, book):
    book("income", 300000, "Girokonto Alex", "Gehalt", on=date(2026, 11, 1))
    book("expense", 95000, "Girokonto Alex", "Miete", on=date(2026, 11, 3))
    book("expense", 90000, "Girokonto Alex", "Miete", on=date(2026, 10, 3))
    book("transfer", 20000, "Girokonto Alex", to="Depot", on=date(2026, 11, 5))
    html = client.get("/stats/month?m=2026-11").text
    assert "November 2026" in html
    for value in ["3.000,00", "950,00", "200,00", "1.850,00"]:  # Einnahmen, Ausgaben, Gespart, Saldo
        assert value in html
    assert "+50,00\u00a0€ ggü. Oktober" in html  # Ausgaben delta
    assert "🏠 Wohnen" in html and "100,0\u00a0%" in html
    assert "/stats/category/" in html and "m=2026-10" in html and "m=2026-12" in html
    income = client.get("/stats/month?m=2026-11&kind=income").text
    assert "💼 Gehalt" in income


def test_month_view_keeps_filters_in_links(client, seed, book):
    acc = seed.account("Bargeld").id
    html = client.get(f"/stats/month?m=2026-11&account={acc}").text.replace("&amp;", "&")
    assert f"m=2026-12&kind=expense&account={acc}" in html
    assert "Filter · aktiv" in html


def test_year_view(client, book):
    book("expense", 1000, "Bargeld", "Supermarkt", on=date(2026, 3, 3))
    book("transfer", 5000, "Girokonto Alex", to="Depot", on=date(2026, 7, 1))
    html = client.get("/stats/year?y=2026").text
    assert '"ausgaben": [0, 0, 1000, 0' in html and '"gespart": [0, 0, 0, 0, 0, 0, 5000' in html
    assert "Monatstabelle" in html and "y=2025" in html


def test_day_view(client, book):
    book("expense", 1250, "Bargeld", "Supermarkt", on=date(2026, 11, 10))
    book("expense", 999, "Bargeld", "Supermarkt", on=date(2026, 11, 11))
    html = client.get("/stats/day?d=2026-11-10").text
    assert "12,50" in html and "9,99" not in html and "Montag" not in html  # 10.11.2026 is a Tuesday
    assert "Dienstag, 10.11.2026" in html
    assert 'class="day"' not in html  # no repeated day heading inside the list


def test_category_drilldown(client, seed, book):
    book("expense", 6000, "Bargeld", "Supermarkt", on=date(2026, 11, 2))
    book("expense", 1000, "Bargeld", "Lebensmittel", on=date(2026, 11, 3))
    lm = seed.category("Lebensmittel").id
    html = client.get(f"/stats/category/{lm}?m=2026-11").text
    assert "Supermarkt" in html and "Ohne Unterkategorie" in html and "70,00" in html
    assert html.count('class="row"') == 2
    year = client.get(f"/stats/category/{lm}?y=2026").text
    assert "2026 · 70,00" in year
    assert client.get("/stats/category/9999").status_code == 404


def test_bad_period_params_fall_back(client):
    for url in ["/stats/month?m=garbage", "/stats/month?m=2026-13", "/stats/year?y=x", "/stats/day?d=nope"]:
        assert client.get(url).status_code == 200
