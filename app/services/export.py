"""CSV export (spec §9): semicolon-separated, UTF-8 with BOM, de-AT number/date format."""

import csv
import io
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fmt
from app.models import Entry, EntryType
from app.services.filters import ENTRY_LOAD_OPTIONS

COLUMNS = ["Datum", "Typ", "Betrag", "Konto", "Zielkonto", "Hauptkategorie", "Unterkategorie", "Tags", "Notiz"]
TYPE_NAMES = {EntryType.income: "Einnahme", EntryType.expense: "Ausgabe", EntryType.transfer: "Umbuchung"}


def entries_csv(db: Session, start: date, end: date) -> bytes:
    """All entries with start <= date <= end, oldest first."""
    entries = db.scalars(
        select(Entry)
        .options(*ENTRY_LOAD_OPTIONS)
        .where(Entry.date >= start, Entry.date <= end)
        .order_by(Entry.date, Entry.id)
    ).unique()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for e in entries:
        cat = e.category
        writer.writerow([
            fmt.date_de(e.date),
            TYPE_NAMES[e.type],
            fmt.amount_input(e.amount_cents),  # "1234,56": a plain number for Excel (de-AT)
            e.account.name,
            e.to_account.name if e.to_account else "",
            cat.main.name if cat else "",
            cat.name if cat and cat.parent else "",
            ", ".join(t.name for t in e.tags),
            e.note or "",
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")
