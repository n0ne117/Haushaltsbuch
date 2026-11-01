from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload
from starlette.datastructures import FormData

from app import fmt
from app.db import get_db
from app.models import Category, CategoryType, Entry, EntryType, Tag
from app.services import lookups
from app.services.entries import EntryData, ValidationError, create_entry, update_entry
from app.templating import is_htmx, render

router = APIRouter()

PAGE_SIZE = 50
UNDO_WINDOW = timedelta(minutes=2)
LAST_ACCOUNT_COOKIE = "last_account"


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def parse_entry_form(form: FormData) -> tuple[EntryData | None, dict[str, str], dict]:
    """Form → EntryData. Returns (data or None, errors, raw values for re-rendering)."""
    values = {
        k: str(form.get(k) or "")
        for k in ("type", "amount", "account_id", "to_account_id", "category_id", "date", "note")
    }
    values["tag_ids"] = [int(t) for t in form.getlist("tags") if str(t).isdigit()]
    errors: dict[str, str] = {}

    try:
        entry_type = EntryType(values["type"] or "expense")
    except ValueError:
        entry_type = EntryType.expense
        errors["type"] = "Ungültige Buchungsart."
    try:
        amount = fmt.parse_amount(values["amount"])
    except ValueError as e:
        amount = 0
        errors["amount"] = str(e)
    try:
        entry_date = date.fromisoformat(values["date"]) if values["date"] else fmt.today()
    except ValueError:
        entry_date = fmt.today()
        errors["date"] = "Ungültiges Datum."
    account_id = _int_or_none(values["account_id"])
    if account_id is None:
        errors["account_id"] = "Bitte ein Konto wählen."

    if errors:
        return None, errors, values
    transfer = entry_type == EntryType.transfer
    return (
        EntryData(
            type=entry_type,
            date=entry_date,
            amount_cents=amount,
            account_id=account_id,
            # Fields belonging to the other entry types are ignored, not rejected.
            to_account_id=_int_or_none(values["to_account_id"]) if transfer else None,
            category_id=None if transfer else _int_or_none(values["category_id"]),
            note=values["note"],
            tag_ids=values["tag_ids"],
        ),
        {},
        values,
    )


def entry_values(entry: Entry) -> dict:
    return {
        "type": entry.type.value,
        "amount": fmt.amount_input(entry.amount_cents),
        "account_id": str(entry.account_id),
        "to_account_id": str(entry.to_account_id or ""),
        "category_id": str(entry.category_id or ""),
        "date": entry.date.isoformat(),
        "note": entry.note or "",
        "tag_ids": [t.id for t in entry.tags],
    }


def form_context(db: Session, values: dict, errors: dict | None = None, entry: Entry | None = None) -> dict:
    accounts = lookups.accounts(db)
    if entry:  # archived accounts stay selectable on their own entries
        for acc in (entry.account, entry.to_account):
            if acc and acc not in accounts:
                accounts.append(acc)
    keep_cat = entry.category_id if entry else None
    return {
        "values": values,
        "errors": errors or {},
        "accounts": accounts,
        "expense_tree": lookups.category_tree(db, CategoryType.expense, include_id=keep_cat),
        "income_tree": lookups.category_tree(db, CategoryType.income, include_id=keep_cat),
        "tags": lookups.tags(db),
    }


def fresh_values(db: Session, request: Request, account_id: int | None = None) -> dict:
    remembered = account_id or _int_or_none(request.cookies.get(LAST_ACCOUNT_COOKIE))
    active = lookups.accounts(db)
    if remembered not in {a.id for a in active}:
        remembered = active[0].id if active else None
    return {
        "type": "expense",
        "amount": "",
        "account_id": str(remembered or ""),
        "to_account_id": "",
        "category_id": "",
        "date": fmt.today().isoformat(),
        "note": "",
        "tag_ids": [],
    }


# --- Quick add ---------------------------------------------------------------


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    return render(request, "home.html", **form_context(db, fresh_values(db, request)))


@router.post("/entries")
async def create(request: Request, db: Session = Depends(get_db)):
    data, errors, values = parse_entry_form(await request.form())
    entry = None
    if data:
        try:
            entry = create_entry(db, data)
        except ValidationError as e:
            errors = e.errors
    if entry is None:
        template = "partials/quick_add.html" if is_htmx(request) else "home.html"
        return render(request, template, 422, **form_context(db, values, errors))

    if is_htmx(request):
        response = render(
            request,
            "partials/quick_add_saved.html",
            entry=entry,
            **form_context(db, fresh_values(db, request, entry.account_id)),
        )
    else:
        response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        LAST_ACCOUNT_COOKIE, str(entry.account_id), max_age=400 * 86400, samesite="lax", httponly=True
    )
    return response


@router.post("/entries/{entry_id:int}/undo")
def undo(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = db.get(Entry, entry_id)
    message = "Rückgängig gemacht."
    if entry is None:
        message = "Buchung existiert nicht mehr."
    elif datetime.now(UTC).replace(tzinfo=None) - entry.created_at > UNDO_WINDOW:
        message = "Zu spät – bitte in den Buchungen löschen."
    else:
        db.delete(entry)
        db.commit()
    return render(request, "partials/toast.html", message=message)


# --- List ----------------------------------------------------------------------


@dataclass
class ListFilters:
    account_ids: list[int]
    tag_ids: list[int]
    q: str

    @classmethod
    def from_request(cls, request: Request) -> "ListFilters":
        qp = request.query_params
        return cls(
            account_ids=[int(v) for v in qp.getlist("account") if v.isdigit()],
            tag_ids=[int(v) for v in qp.getlist("tag") if v.isdigit()],
            q=qp.get("q", "").strip(),
        )

    def params(self) -> list[tuple[str, str]]:
        return (
            [("account", str(a)) for a in self.account_ids]
            + [("tag", str(t)) for t in self.tag_ids]
            + ([("q", self.q)] if self.q else [])
        )

    @property
    def active(self) -> bool:
        return bool(self.account_ids or self.tag_ids or self.q)


def query_entries(db: Session, f: ListFilters, offset: int, limit: int) -> list[Entry]:
    stmt = (
        select(Entry)
        .options(
            joinedload(Entry.account),
            joinedload(Entry.to_account),
            joinedload(Entry.category).joinedload(Category.parent),
            selectinload(Entry.tags),
        )
        .order_by(Entry.date.desc(), Entry.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if f.account_ids:
        stmt = stmt.where(or_(Entry.account_id.in_(f.account_ids), Entry.to_account_id.in_(f.account_ids)))
    if f.tag_ids:
        stmt = stmt.where(Entry.tags.any(Tag.id.in_(f.tag_ids)))
    if f.q:
        stmt = stmt.where(Entry.note.contains(f.q, autoescape=True))
    return list(db.scalars(stmt).unique())


def rows_context(db: Session, f: ListFilters, offset: int, prev_date: date | None) -> dict:
    entries = query_entries(db, f, offset, PAGE_SIZE + 1)
    next_url = None
    if len(entries) > PAGE_SIZE:
        entries = entries[:PAGE_SIZE]
        params = f.params() + [("offset", str(offset + PAGE_SIZE)), ("prev", entries[-1].date.isoformat())]
        next_url = "/entries/rows?" + urlencode(params)
    return {"entries": entries, "prev_date": prev_date, "next_url": next_url, "offset": offset}


@router.get("/entries")
def entry_list(request: Request, db: Session = Depends(get_db)):
    f = ListFilters.from_request(request)
    return render(
        request,
        "entries/list.html",
        filters=f,
        accounts=lookups.accounts(db, archived=True),
        tags=lookups.tags(db),
        **rows_context(db, f, 0, None),
    )


@router.get("/entries/rows")
def entry_rows(request: Request, db: Session = Depends(get_db)):
    f = ListFilters.from_request(request)
    offset = _int_or_none(request.query_params.get("offset")) or 0
    try:
        prev_date = date.fromisoformat(request.query_params.get("prev", ""))
    except ValueError:
        prev_date = None
    return render(request, "entries/_rows.html", **rows_context(db, f, offset, prev_date))


# --- Edit / delete ---------------------------------------------------------------


def _get_entry(db: Session, entry_id: int) -> Entry:
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(404)
    return entry


@router.get("/entries/{entry_id:int}")
def edit(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = _get_entry(db, entry_id)
    return render(request, "entries/edit.html", entry=entry, **form_context(db, entry_values(entry), entry=entry))


@router.post("/entries/{entry_id:int}")
async def update(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = _get_entry(db, entry_id)
    data, errors, values = parse_entry_form(await request.form())
    if data:
        try:
            update_entry(db, entry, data)
            return RedirectResponse("/entries", status_code=303)
        except ValidationError as e:
            errors = e.errors
    return render(request, "entries/edit.html", 422, entry=entry, **form_context(db, values, errors, entry))


@router.post("/entries/{entry_id:int}/delete")
def delete(entry_id: int, db: Session = Depends(get_db)):
    db.delete(_get_entry(db, entry_id))
    db.commit()
    return RedirectResponse("/entries", status_code=303)
