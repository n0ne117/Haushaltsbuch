from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import (
    Entry,
    EntryType,
    Frequency,
    OccurrenceStatus,
    RecurringOccurrence,
    RecurringTemplate,
)
from app.services import recurring

HX = {"HX-Request": "true"}


def _template(**kw) -> RecurringTemplate:
    base = dict(name="T", type=EntryType.expense, amount_cents=100, account_id=1, category_id=None,
                frequency=Frequency.monthly, day=1, start_date=date(2026, 1, 1), end_date=None, active=True)
    base.update(kw)
    return RecurringTemplate(**base)


# --- Schedule ----------------------------------------------------------------------


def test_month_end_clamping():
    t = _template(day=31, start_date=date(2027, 1, 1))  # 2028 is a leap year
    dates = recurring.due_dates(t, date(2028, 4, 30))
    assert date(2027, 2, 28) in dates and date(2027, 4, 30) in dates
    assert date(2028, 2, 29) in dates and date(2028, 4, 30) in dates
    assert date(2027, 3, 31) in dates


def test_monthly_starts_after_start_date():
    t = _template(day=10, start_date=date(2026, 1, 15))
    assert recurring.due_dates(t, date(2026, 3, 31)) == [date(2026, 2, 10), date(2026, 3, 10)]


def test_quarterly_and_yearly():
    q = _template(frequency=Frequency.quarterly, day=5, start_date=date(2026, 2, 1))
    assert recurring.due_dates(q, date(2026, 12, 31)) == [
        date(2026, 2, 5), date(2026, 5, 5), date(2026, 8, 5), date(2026, 11, 5)]
    y = _template(frequency=Frequency.yearly, day=29, start_date=date(2028, 2, 1))
    assert recurring.due_dates(y, date(2030, 12, 31)) == [date(2028, 2, 29), date(2029, 2, 28), date(2030, 2, 28)]


def test_weekly():
    t = _template(frequency=Frequency.weekly, day=0, start_date=date(2026, 11, 4))  # Wed → first Monday 9th
    assert recurring.due_dates(t, date(2026, 11, 23)) == [date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 23)]


def test_end_date():
    t = _template(day=1, start_date=date(2026, 1, 1), end_date=date(2026, 3, 15))
    assert recurring.due_dates(t, date(2026, 12, 31)) == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert recurring.next_due(t, date(2026, 3, 2)) is None


# --- Generation ----------------------------------------------------------------------


@pytest.fixture
def miete(db, seed):
    t = _template(name="Miete", amount_cents=95000, account_id=seed.account("Girokonto Alex").id,
                  category_id=seed.category("Miete").id, day=31, start_date=date(2027, 1, 1))
    db.add(t)
    db.commit()
    return t


def _occurrences(db, t):
    return db.scalars(select(RecurringOccurrence).where(RecurringOccurrence.recurring_id == t.id)
                      .order_by(RecurringOccurrence.due_date)).all()


def test_generate_creates_pending_up_to_today(db, miete):
    recurring.generate(db, date(2027, 4, 30))
    assert [o.due_date for o in _occurrences(db, miete)] == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]
    assert {o.status for o in _occurrences(db, miete)} == {OccurrenceStatus.pending}
    assert db.scalar(select(func.count()).select_from(Entry)) == 0  # never auto-booked


def test_generate_is_idempotent(db, miete):
    recurring.generate(db, date(2027, 3, 31))
    recurring.generate(db, date(2027, 3, 31))
    assert len(_occurrences(db, miete)) == 3


def test_restart_does_not_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db as app_db
    for start in range(2):  # two app starts against the same database
        with TestClient(create_app()) as c:
            if start == 0:
                with app_db.session() as s:
                    s.add(_template(name="Abo", category_id=None, type=EntryType.transfer, account_id=1,
                                    to_account_id=4, day=1, start_date=date(2026, 1, 1)))
                    s.commit()
            c.get("/")
    with app_db.session() as s:
        dates = s.scalars(select(RecurringOccurrence.due_date)).all()
        assert len(dates) == len(set(dates)) > 0


def test_booked_and_skipped_are_kept_when_schedule_changes(db, miete):
    recurring.generate(db, date(2027, 3, 31))
    jan, feb, mar = _occurrences(db, miete)
    recurring.book(db, jan)
    recurring.skip(db, feb)
    miete.day = 1  # schedule change → stale pending (Mar 31) disappears, new dates appear
    recurring.sync_template(db, miete, date(2027, 3, 31))
    db.commit()
    by_date = {o.due_date: o.status for o in _occurrences(db, miete)}
    assert by_date[date(2027, 1, 31)] == OccurrenceStatus.booked
    assert by_date[date(2027, 2, 28)] == OccurrenceStatus.skipped
    assert date(2027, 3, 31) not in by_date
    assert by_date[date(2027, 3, 1)] == OccurrenceStatus.pending


def test_deactivating_removes_pending(db, miete):
    recurring.generate(db, date(2027, 2, 28))
    miete.active = False
    recurring.generate(db, date(2027, 2, 28))
    assert _occurrences(db, miete) == []


def test_book_uses_template_values(db, seed, miete):
    recurring.generate(db, date(2027, 1, 31))
    (occ,) = _occurrences(db, miete)
    entry = recurring.book(db, occ)
    assert (entry.amount_cents, entry.date, entry.category.name, entry.recurring_id) == (
        95000, date(2027, 1, 31), "Miete", miete.id)
    assert occ.status == OccurrenceStatus.booked and occ.entry_id == entry.id


# --- Web -------------------------------------------------------------------------------


@pytest.fixture
def due_today(db, seed):
    from app import fmt
    t = _template(name="Strom", amount_cents=6000, account_id=seed.account("Girokonto Alex").id,
                  category_id=seed.category("Strom").id, day=fmt.today().day, start_date=fmt.today())
    db.add(t)
    db.commit()
    return t


def test_home_shows_pending_and_confirm(client, db, due_today):
    page = client.get("/")
    assert "Fällig" in page.text and "Strom" in page.text
    (occ,) = _occurrences(db, due_today)
    r = client.post(f"/recurring/occurrences/{occ.id}/confirm", headers=HX)
    assert "Gebucht: Strom" in r.text and "Fällig" not in r.text.split('id="toast"')[0]
    db.expunge_all()
    assert db.scalars(select(Entry)).one().amount_cents == 6000

    # Undo puts the occurrence back to pending.
    entry = db.scalars(select(Entry)).one()
    r = client.post(f"/entries/{entry.id}/undo", headers=HX)
    assert 'id="pending"' in r.text and "Strom" in r.text
    db.expunge_all()
    assert db.get(RecurringOccurrence, occ.id).status == OccurrenceStatus.pending
    assert db.scalar(select(func.count()).select_from(Entry)) == 0


def test_skip_and_unskip(client, db, due_today):
    client.get("/")
    (occ,) = _occurrences(db, due_today)
    client.post(f"/recurring/occurrences/{occ.id}/skip", headers=HX)
    db.expunge_all()
    assert db.get(RecurringOccurrence, occ.id).status == OccurrenceStatus.skipped
    assert "Fällig" not in client.get("/").text
    client.post(f"/recurring/occurrences/{occ.id}/unskip", headers=HX)
    db.expunge_all()
    assert db.get(RecurringOccurrence, occ.id).status == OccurrenceStatus.pending


def test_book_with_edits(client, db, seed, due_today):
    client.get("/")
    (occ,) = _occurrences(db, due_today)
    page = client.get(f"/recurring/occurrences/{occ.id}")
    assert 'value="60,00"' in page.text and "Buchen" in page.text
    r = client.post(f"/recurring/occurrences/{occ.id}", follow_redirects=False, data={
        "type": "expense", "amount": "71,30", "account_id": seed.account("Girokonto Alex").id,
        "category_id": seed.category("Strom").id, "date": occ.due_date.isoformat(), "note": "Nachzahlung",
    })
    assert r.status_code == 303
    db.expunge_all()
    entry = db.scalars(select(Entry)).one()
    assert (entry.amount_cents, entry.note, entry.recurring_id) == (7130, "Nachzahlung", due_today.id)
    assert db.get(RecurringOccurrence, occ.id).status == OccurrenceStatus.booked
    # The template itself is unchanged.
    assert db.get(RecurringTemplate, due_today.id).amount_cents == 6000


def _tpl_form(seed, **kw):
    base = {"name": "Sparplan", "type": "transfer", "amount": "200",
            "account_id": seed.account("Girokonto Alex").id, "to_account_id": seed.account("Depot").id,
            "frequency": "monthly", "day": "5", "weekday": "0", "start_date": "2026-01-01",
            "end_date": "", "active": "on"}
    base.update(kw)
    return base


def test_template_crud(client, db, seed):
    for url in ["/settings/recurring", "/settings/recurring/new"]:
        assert client.get(url).status_code == 200
    r = client.post("/settings/recurring/new", data=_tpl_form(seed), follow_redirects=False)
    assert r.status_code == 303
    t = db.scalars(select(RecurringTemplate)).one()
    assert (t.type, t.amount_cents, t.day, t.to_account.name) == (EntryType.transfer, 20000, 5, "Depot")
    assert len(_occurrences(db, t)) > 0  # generated right away (start in the past)
    assert "Monatlich am 5." in client.get("/settings/recurring").text
    assert client.get(f"/settings/recurring/{t.id}").status_code == 200

    r = client.post(f"/settings/recurring/{t.id}", data=_tpl_form(seed, frequency="weekly", weekday="4"),
                    follow_redirects=False)
    assert r.status_code == 303
    db.expunge_all()
    t = db.get(RecurringTemplate, t.id)
    assert (t.frequency, t.day) == (Frequency.weekly, 4)
    assert all(o.due_date.weekday() == 4 for o in _occurrences(db, t))

    assert client.post(f"/settings/recurring/{t.id}/delete", follow_redirects=False).status_code == 303
    db.expunge_all()
    assert db.scalar(select(func.count()).select_from(RecurringOccurrence)) == 0


def test_template_validation(client, seed):
    r = client.post("/settings/recurring/new", data=_tpl_form(
        seed, name="", day="32", to_account_id=seed.account("Girokonto Alex").id, end_date="2025-01-01"))
    assert r.status_code == 422
    for msg in ["Bitte einen Namen", "zwischen 1 und 31", "verschieden", "vor dem Startdatum"]:
        assert msg in r.text


def test_account_used_by_template_cannot_be_deleted(client, db, seed, due_today):
    acc = seed.account("Girokonto Alex")
    assert client.post(f"/settings/accounts/{acc.id}/delete").status_code == 409
