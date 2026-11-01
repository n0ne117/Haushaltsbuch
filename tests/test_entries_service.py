from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Entry, EntryType
from app.services.entries import EntryData, ValidationError, create_entry, update_entry

D = date(2026, 10, 15)


def test_expense_ok(db, seed):
    e = create_entry(db, EntryData(EntryType.expense, D, 1250, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id, note="  Wocheneinkauf ",
                                   tag_ids=[seed.tag("Kreditkarte").id]))
    assert e.id and e.note == "Wocheneinkauf" and [t.name for t in e.tags] == ["Kreditkarte"]


def test_category_type_must_match(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.income, D, 100, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id))
    assert "category_id" in exc.value.errors


def test_income_requires_category(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.income, D, 100, seed.account("Bargeld").id))
    assert "category_id" in exc.value.errors


def test_transfer_ok(db, seed):
    e = create_entry(db, EntryData(EntryType.transfer, D, 20000, seed.account("Girokonto Alex").id,
                                   to_account_id=seed.account("Depot").id))
    assert e.category_id is None and e.to_account.name == "Depot"


def test_transfer_same_account_rejected(db, seed):
    acc = seed.account("Bargeld").id
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.transfer, D, 100, acc, to_account_id=acc))
    assert "to_account_id" in exc.value.errors


def test_transfer_requires_target(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.transfer, D, 100, seed.account("Bargeld").id))
    assert "to_account_id" in exc.value.errors


def test_transfer_must_not_have_category(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.transfer, D, 100, seed.account("Bargeld").id,
                                   to_account_id=seed.account("Depot").id,
                                   category_id=seed.category("Supermarkt").id))
    assert "category_id" in exc.value.errors


def test_expense_must_not_have_target_account(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.expense, D, 100, seed.account("Bargeld").id,
                                   to_account_id=seed.account("Depot").id,
                                   category_id=seed.category("Supermarkt").id))
    assert "to_account_id" in exc.value.errors


def test_amount_must_be_positive(db, seed):
    with pytest.raises(ValidationError) as exc:
        create_entry(db, EntryData(EntryType.expense, D, 0, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id))
    assert "amount" in exc.value.errors


def test_db_constraint_backs_up_transfer_rules(db, seed):
    acc = seed.account("Bargeld").id
    db.add(Entry(type=EntryType.transfer, date=D, amount_cents=100, account_id=acc, to_account_id=acc))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_update_switches_type(db, seed):
    e = create_entry(db, EntryData(EntryType.expense, D, 5000, seed.account("Girokonto Alex").id,
                                   category_id=seed.category("Supermarkt").id))
    update_entry(db, e, EntryData(EntryType.transfer, D, 5000, seed.account("Girokonto Alex").id,
                                  to_account_id=seed.account("Bargeld").id))
    assert e.type == EntryType.transfer and e.category_id is None
