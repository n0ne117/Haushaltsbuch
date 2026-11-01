from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app import fmt
from app.db import get_db
from app.models import Frequency, OccurrenceStatus, RecurringOccurrence, RecurringTemplate, Tag
from app.routes.entries import form_context, parse_entry_form
from app.services import lookups, recurring
from app.services.entries import ValidationError, validate
from app.templating import render

router = APIRouter()


def _404():
    raise HTTPException(404)


# --- Templates (Einstellungen → Daueraufträge) ------------------------------------


def template_values(t: RecurringTemplate | None) -> dict:
    if t is None:
        today = fmt.today()
        return {
            "name": "", "type": "expense", "amount": "", "account_id": "", "to_account_id": "",
            "category_id": "", "note": "", "tag_ids": [], "frequency": "monthly",
            "day": str(today.day), "weekday": str(today.weekday()),
            "start_date": today.isoformat(), "end_date": "", "active": True,
        }
    weekly = t.frequency == Frequency.weekly
    return {
        "name": t.name,
        "type": t.type.value,
        "amount": fmt.amount_input(t.amount_cents),
        "account_id": str(t.account_id),
        "to_account_id": str(t.to_account_id or ""),
        "category_id": str(t.category_id or ""),
        "note": t.note or "",
        "tag_ids": [tag.id for tag in t.tags],
        "frequency": t.frequency.value,
        "day": str(t.start_date.day if weekly else t.day),
        "weekday": str(t.day if weekly else t.start_date.weekday()),
        "start_date": t.start_date.isoformat(),
        "end_date": t.end_date.isoformat() if t.end_date else "",
        "active": t.active,
    }


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_template_form(db: Session, form: FormData):
    data, errors, values = parse_entry_form(form)
    values.update(
        name=str(form.get("name") or "").strip(),
        frequency=str(form.get("frequency") or ""),
        day=str(form.get("day") or ""),
        weekday=str(form.get("weekday") or ""),
        start_date=str(form.get("start_date") or ""),
        end_date=str(form.get("end_date") or ""),
        active=form.get("active") == "on",
    )
    if not values["name"]:
        errors["name"] = "Bitte einen Namen eingeben (z. B. „Miete“)."
    try:
        frequency = Frequency(values["frequency"])
    except ValueError:
        frequency = None
        errors["frequency"] = "Bitte einen Rhythmus wählen."

    day = None
    if frequency == Frequency.weekly:
        day = int(values["weekday"]) if values["weekday"].isdigit() else None
        if day is None or not 0 <= day <= 6:
            errors["day"] = "Bitte einen Wochentag wählen."
    elif frequency is not None:
        day = int(values["day"]) if values["day"].isdigit() else None
        if day is None or not 1 <= day <= 31:
            errors["day"] = "Bitte einen Tag zwischen 1 und 31 eingeben."

    start = _parse_date(values["start_date"])
    if start is None:
        errors["start_date"] = "Bitte ein Startdatum wählen."
    end = _parse_date(values["end_date"])
    if values["end_date"] and end is None:
        errors["end_date"] = "Ungültiges Datum."
    elif start and end and end < start:
        errors["end_date"] = "Das Enddatum liegt vor dem Startdatum."

    if data is not None:
        try:
            validate(db, data)
        except ValidationError as e:
            errors.update(e.errors)
    schedule = {"frequency": frequency, "day": day, "start_date": start, "end_date": end}
    return data, schedule, errors, values


def _template_page(request, db, t: RecurringTemplate | None, values, errors, status=200):
    return render(
        request, "settings/recurring_form.html", status,
        template=t, frequencies=recurring.FREQUENCY_LABELS, weekdays=recurring.WEEKDAY_LABELS,
        **form_context(db, values, errors, entry=t),
    )


@router.get("/settings/recurring")
def template_list(request: Request, db: Session = Depends(get_db)):
    today = fmt.today()
    templates = list(db.scalars(select(RecurringTemplate).order_by(RecurringTemplate.active.desc(),
                                                                   RecurringTemplate.name)))
    rows = [(t, recurring.describe(t), recurring.next_due(t, today) if t.active else None) for t in templates]
    return render(request, "settings/recurring.html", rows=rows)


@router.get("/settings/recurring/new")
def template_new(request: Request, db: Session = Depends(get_db)):
    values = template_values(None)
    accounts = lookups.accounts(db)
    if accounts:
        values["account_id"] = str(accounts[0].id)
    return _template_page(request, db, None, values, {})


@router.get("/settings/recurring/{template_id:int}")
def template_edit(template_id: int, request: Request, db: Session = Depends(get_db)):
    t = db.get(RecurringTemplate, template_id) or _404()
    return _template_page(request, db, t, template_values(t), {})


@router.post("/settings/recurring/new")
@router.post("/settings/recurring/{template_id:int}")
async def template_save(request: Request, template_id: int | None = None, db: Session = Depends(get_db)):
    t = db.get(RecurringTemplate, template_id) or _404() if template_id else None
    data, schedule, errors, values = parse_template_form(db, await request.form())
    if errors:
        return _template_page(request, db, t, values, errors, 422)

    if t is None:
        t = RecurringTemplate()
        db.add(t)
    t.name = values["name"]
    t.type = data.type
    t.amount_cents = data.amount_cents
    t.account_id = data.account_id
    t.to_account_id = data.to_account_id
    t.category_id = data.category_id
    t.note = (data.note or "").strip() or None
    t.tags = list(db.scalars(select(Tag).where(Tag.id.in_(data.tag_ids)))) if data.tag_ids else []
    t.frequency = schedule["frequency"]
    t.day = schedule["day"]
    t.start_date = schedule["start_date"]
    t.end_date = schedule["end_date"]
    t.active = values["active"]
    db.flush()
    recurring.sync_template(db, t, fmt.today())
    db.commit()
    return RedirectResponse("/settings/recurring", status_code=303)


@router.post("/settings/recurring/{template_id:int}/delete")
def template_delete(template_id: int, db: Session = Depends(get_db)):
    db.delete(db.get(RecurringTemplate, template_id) or _404())  # occurrences cascade; entries stay
    db.commit()
    return RedirectResponse("/settings/recurring", status_code=303)


# --- Pending occurrences (home screen) ----------------------------------------------


def _occurrence(db: Session, occ_id: int) -> RecurringOccurrence:
    return db.get(RecurringOccurrence, occ_id) or _404()


def _pending_response(request, db, message: str, undo_url: str | None = None):
    return render(request, "partials/pending_action.html", pending=recurring.pending(db),
                  message=message, undo_url=undo_url)


@router.post("/recurring/occurrences/{occ_id:int}/confirm")
def occurrence_confirm(occ_id: int, request: Request, db: Session = Depends(get_db)):
    occ = _occurrence(db, occ_id)
    try:
        entry = recurring.book(db, occ)
    except ValidationError as e:
        db.rollback()
        return _pending_response(request, db, " ".join(e.errors.values()))
    return _pending_response(request, db, f"Gebucht: {occ.template.name}", f"/entries/{entry.id}/undo")


@router.post("/recurring/occurrences/{occ_id:int}/skip")
def occurrence_skip(occ_id: int, request: Request, db: Session = Depends(get_db)):
    occ = _occurrence(db, occ_id)
    recurring.skip(db, occ)
    return _pending_response(request, db, f"Übersprungen: {occ.template.name}",
                             f"/recurring/occurrences/{occ.id}/unskip")


@router.post("/recurring/occurrences/{occ_id:int}/unskip")
def occurrence_unskip(occ_id: int, request: Request, db: Session = Depends(get_db)):
    occ = _occurrence(db, occ_id)
    if occ.status == OccurrenceStatus.skipped:
        occ.status = OccurrenceStatus.pending
        db.commit()
    return _pending_response(request, db, "Rückgängig gemacht.")


@router.get("/recurring/occurrences/{occ_id:int}")
def occurrence_edit(occ_id: int, request: Request, db: Session = Depends(get_db)):
    occ = _occurrence(db, occ_id)
    if occ.status != OccurrenceStatus.pending:
        return RedirectResponse("/", status_code=303)
    values = template_values(occ.template) | {"date": occ.due_date.isoformat()}
    return render(request, "recurring_book.html", occ=occ,
                  **form_context(db, values, entry=occ.template))


@router.post("/recurring/occurrences/{occ_id:int}")
async def occurrence_book_edited(occ_id: int, request: Request, db: Session = Depends(get_db)):
    occ = _occurrence(db, occ_id)
    data, errors, values = parse_entry_form(await request.form())
    if data is not None:
        try:
            recurring.book(db, occ, data)
            return RedirectResponse("/", status_code=303)
        except ValidationError as e:
            db.rollback()
            errors = e.errors
    return render(request, "recurring_book.html", 422, occ=occ,
                  **form_context(db, values, errors, entry=occ.template))
