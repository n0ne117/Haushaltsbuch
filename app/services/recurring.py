"""Recurring templates (spec §5.5/5.6): due-date schedule, occurrence generation, booking."""

import calendar
from collections.abc import Iterator
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, joinedload

from app.models import Category, Entry, Frequency, OccurrenceStatus, RecurringOccurrence, RecurringTemplate
from app.services.entries import EntryData, ValidationError, create_entry

MONTH_STEP = {Frequency.monthly: 1, Frequency.quarterly: 3, Frequency.yearly: 12}
WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
FREQUENCY_LABELS = {
    Frequency.weekly: "Wöchentlich",
    Frequency.monthly: "Monatlich",
    Frequency.quarterly: "Quartalsweise",
    Frequency.yearly: "Jährlich",
}


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def iter_due_dates(t: RecurringTemplate) -> Iterator[date]:
    """All due dates from start_date on (until end_date, if set).

    Weekly: every `day` (0 = Monday). Monthly/quarterly/yearly: on day `day` of the month,
    clamped to the month's last day, stepping from the month of start_date.
    """
    if t.frequency == Frequency.weekly:
        d = t.start_date + timedelta(days=(t.day - t.start_date.weekday()) % 7)
        step = timedelta(days=7)
        while t.end_date is None or d <= t.end_date:
            yield d
            d += step
        return

    months = MONTH_STEP[t.frequency]
    i = 0
    while True:
        m = t.start_date.month - 1 + i * months
        d = _clamped(t.start_date.year + m // 12, m % 12 + 1, t.day)
        if t.end_date is not None and d > t.end_date:
            return
        if d >= t.start_date:
            yield d
        i += 1


def due_dates(t: RecurringTemplate, until: date) -> list[date]:
    out = []
    for d in iter_due_dates(t):
        if d > until:
            break
        out.append(d)
    return out


def next_due(t: RecurringTemplate, on_or_after: date) -> date | None:
    return next((d for d in iter_due_dates(t) if d >= on_or_after), None)


def describe(t: RecurringTemplate) -> str:
    if t.frequency == Frequency.weekly:
        return f"Wöchentlich am {WEEKDAY_LABELS[t.day]}"
    return f"{FREQUENCY_LABELS[t.frequency]} am {t.day}."


def sync_template(db: Session, t: RecurringTemplate, today: date) -> None:
    """Make pending occurrences match the template's schedule up to today.

    Idempotent: never touches booked/skipped occurrences, never creates duplicates
    (unique on recurring_id + due_date). Stale pending ones (template changed or
    deactivated) are removed.
    """
    wanted = set(due_dates(t, today)) if t.active else set()
    existing = {
        o.due_date: o
        for o in db.scalars(select(RecurringOccurrence).where(RecurringOccurrence.recurring_id == t.id))
    }
    for d, occ in existing.items():
        if occ.status == OccurrenceStatus.pending and d not in wanted:
            db.delete(occ)
    missing = sorted(wanted - existing.keys())
    if missing:
        db.execute(
            insert(RecurringOccurrence)
            .values([{"recurring_id": t.id, "due_date": d, "status": OccurrenceStatus.pending} for d in missing])
            .on_conflict_do_nothing(index_elements=["recurring_id", "due_date"])
        )


def generate(db: Session, today: date) -> None:
    for t in db.scalars(select(RecurringTemplate)):
        sync_template(db, t, today)
    db.commit()


def pending(db: Session) -> list[RecurringOccurrence]:
    return list(
        db.scalars(
            select(RecurringOccurrence)
            .where(RecurringOccurrence.status == OccurrenceStatus.pending)
            .options(
                joinedload(RecurringOccurrence.template).joinedload(RecurringTemplate.account),
                joinedload(RecurringOccurrence.template).joinedload(RecurringTemplate.to_account),
                joinedload(RecurringOccurrence.template)
                .joinedload(RecurringTemplate.category)
                .joinedload(Category.parent),
            )
            .order_by(RecurringOccurrence.due_date, RecurringOccurrence.id)
        ).unique()
    )


def template_entry_data(t: RecurringTemplate, on: date) -> EntryData:
    return EntryData(
        type=t.type,
        date=on,
        amount_cents=t.amount_cents,
        account_id=t.account_id,
        to_account_id=t.to_account_id,
        category_id=t.category_id,
        note=t.note,
        tag_ids=[tag.id for tag in t.tags],
    )


def book(db: Session, occ: RecurringOccurrence, data: EntryData | None = None) -> Entry:
    """Book a pending occurrence, as-is from the template or with edited values."""
    if occ.status != OccurrenceStatus.pending:
        raise ValidationError({"occurrence": "Diese Buchung wurde bereits erledigt."})
    data = data or template_entry_data(occ.template, occ.due_date)
    data.recurring_id = occ.recurring_id
    entry = create_entry(db, data, commit=False)
    occ.status = OccurrenceStatus.booked
    occ.entry_id = entry.id
    db.commit()
    return entry


def skip(db: Session, occ: RecurringOccurrence) -> None:
    if occ.status == OccurrenceStatus.pending:
        occ.status = OccurrenceStatus.skipped
        db.commit()


def unbook(db: Session, entry: Entry) -> RecurringOccurrence | None:
    """Before deleting an entry via undo: put its occurrence back to pending."""
    occ = db.scalars(select(RecurringOccurrence).where(RecurringOccurrence.entry_id == entry.id)).first()
    if occ is not None:
        occ.status = OccurrenceStatus.pending
        occ.entry_id = None
    return occ
