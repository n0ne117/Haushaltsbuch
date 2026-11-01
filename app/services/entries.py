from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Category, Entry, EntryType, Tag


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


@dataclass
class EntryData:
    type: EntryType
    date: date
    amount_cents: int
    account_id: int
    to_account_id: int | None = None
    category_id: int | None = None
    note: str | None = None
    tag_ids: list[int] = field(default_factory=list)


def validate(db: Session, data: EntryData) -> None:
    """Spec §5.4 rules. Shared by entries and recurring templates."""
    errors: dict[str, str] = {}

    if data.amount_cents <= 0:
        errors["amount"] = "Der Betrag muss größer als 0 sein."
    if db.get(Account, data.account_id) is None:
        errors["account_id"] = "Bitte ein Konto wählen."

    if data.type == EntryType.transfer:
        if data.category_id is not None:
            errors["category_id"] = "Umbuchungen haben keine Kategorie."
        if data.to_account_id is None or db.get(Account, data.to_account_id) is None:
            errors["to_account_id"] = "Bitte ein Zielkonto wählen."
        elif data.to_account_id == data.account_id:
            errors["to_account_id"] = "Quell- und Zielkonto müssen verschieden sein."
    else:
        if data.to_account_id is not None:
            errors["to_account_id"] = "Nur Umbuchungen haben ein Zielkonto."
        category = db.get(Category, data.category_id) if data.category_id is not None else None
        if category is None:
            errors["category_id"] = "Bitte eine Kategorie wählen."
        elif category.type.value != data.type.value:
            errors["category_id"] = "Die Kategorie passt nicht zur Buchungsart."

    if data.tag_ids:
        found = db.scalars(select(Tag.id).where(Tag.id.in_(data.tag_ids))).all()
        if len(set(found)) != len(set(data.tag_ids)):
            errors["tags"] = "Unbekanntes Tag."

    if errors:
        raise ValidationError(errors)


def _apply(db: Session, entry: Entry, data: EntryData) -> None:
    entry.type = data.type
    entry.date = data.date
    entry.amount_cents = data.amount_cents
    entry.account_id = data.account_id
    entry.to_account_id = data.to_account_id
    entry.category_id = data.category_id
    entry.note = (data.note or "").strip() or None
    entry.tags = list(db.scalars(select(Tag).where(Tag.id.in_(data.tag_ids)))) if data.tag_ids else []


def create_entry(db: Session, data: EntryData) -> Entry:
    validate(db, data)
    entry = Entry()
    _apply(db, entry, data)
    db.add(entry)
    db.commit()
    return entry


def update_entry(db: Session, entry: Entry, data: EntryData) -> Entry:
    validate(db, data)
    _apply(db, entry, data)
    db.commit()
    return entry
