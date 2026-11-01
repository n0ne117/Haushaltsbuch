import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account, AccountKind, Category, CategoryType, Tag, entry_tags
from app.services import lookups
from app.templating import render

router = APIRouter(prefix="/settings")

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _next_sort(db: Session, column, *where) -> int:
    return (db.scalar(select(func.max(column)).where(*where)) or 0) + 1


async def _reorder(request: Request, db: Session, model) -> Response:
    ids = [int(i) for i in (await request.form()).getlist("ids") if str(i).isdigit()]
    for pos, obj_id in enumerate(ids):
        db.execute(update(model).where(model.id == obj_id).values(sort_order=pos))
    db.commit()
    return Response(status_code=204)


@router.get("")
def index(request: Request):
    return render(request, "settings/index.html")


# --- Accounts --------------------------------------------------------------------


@router.get("/accounts")
def accounts(request: Request, db: Session = Depends(get_db)):
    return render(request, "settings/accounts.html", accounts=lookups.accounts(db, archived=True))


@router.post("/accounts/reorder")
async def accounts_reorder(request: Request, db: Session = Depends(get_db)):
    return await _reorder(request, db, Account)


def _account_page(request, db, account: Account | None, values: dict, errors: dict, status=200):
    in_use = account is not None and lookups.account_in_use(db, account.id)
    return render(
        request, "settings/account_form.html", status,
        account=account, values=values, errors=errors, in_use=in_use, kinds=list(AccountKind),
    )


@router.get("/accounts/new")
def account_new(request: Request, db: Session = Depends(get_db)):
    return _account_page(request, db, None, {"kind": "checking"}, {})


@router.get("/accounts/{account_id:int}")
def account_edit(account_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Account, account_id) or _404()
    values = {"name": a.name, "owner": a.owner or "", "kind": a.kind.value, "archived": a.archived}
    return _account_page(request, db, a, values, {})


@router.post("/accounts/new")
@router.post("/accounts/{account_id:int}")
async def account_save(request: Request, account_id: int | None = None, db: Session = Depends(get_db)):
    account = db.get(Account, account_id) or _404() if account_id else None
    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "owner": str(form.get("owner", "")).strip(),
        "kind": str(form.get("kind", "")),
        "archived": form.get("archived") == "on",
    }
    errors = {}
    if not values["name"]:
        errors["name"] = "Bitte einen Namen eingeben."
    elif db.scalar(select(Account.id).where(Account.name == values["name"], Account.id != account_id)):
        errors["name"] = "Ein Konto mit diesem Namen gibt es schon."
    if values["kind"] not in {k.value for k in AccountKind}:
        errors["kind"] = "Bitte eine Kontoart wählen."
    if errors:
        return _account_page(request, db, account, values, errors, 422)

    if account is None:
        account = Account(sort_order=_next_sort(db, Account.sort_order))
        db.add(account)
    account.name = values["name"]
    account.owner = values["owner"] or None
    account.kind = AccountKind(values["kind"])
    account.archived = values["archived"]
    db.commit()
    return _redirect("/settings/accounts")


@router.post("/accounts/{account_id:int}/delete")
def account_delete(account_id: int, request: Request, db: Session = Depends(get_db)):
    account = db.get(Account, account_id) or _404()
    if lookups.account_in_use(db, account.id):
        values = {"name": account.name, "owner": account.owner or "", "kind": account.kind.value,
                  "archived": account.archived}
        return _account_page(request, db, account, values,
                             {"delete": "Wird verwendet – bitte archivieren statt löschen."}, 409)
    db.delete(account)
    db.commit()
    return _redirect("/settings/accounts")


# --- Categories ------------------------------------------------------------------


@router.get("/categories")
def categories(request: Request, db: Session = Depends(get_db)):
    return render(
        request,
        "settings/categories.html",
        expense_tree=lookups.category_tree(db, CategoryType.expense, archived=True),
        income_tree=lookups.category_tree(db, CategoryType.income, archived=True),
    )


@router.post("/categories/reorder")
async def categories_reorder(request: Request, db: Session = Depends(get_db)):
    return await _reorder(request, db, Category)


def _category_page(request, db, category: Category | None, values: dict, errors: dict, status=200):
    parents = [
        main for main, _ in lookups.category_tree(db, archived=True)
        if category is None or main.id != category.id
    ]
    return render(
        request, "settings/category_form.html", status,
        category=category, values=values, errors=errors, parents=parents,
        in_use=category is not None and lookups.category_in_use(db, category),
    )


@router.get("/categories/new")
def category_new(request: Request, db: Session = Depends(get_db)):
    qp = request.query_params
    parent = db.get(Category, int(qp["parent"])) if qp.get("parent", "").isdigit() else None
    values = {
        "name": "", "emoji": "", "archived": False,
        "type": parent.type.value if parent else qp.get("type", "expense"),
        "parent_id": str(parent.id) if parent else "",
        "color": parent.color if parent else "#888888",
    }
    return _category_page(request, db, None, values, {})


@router.get("/categories/{category_id:int}")
def category_edit(category_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Category, category_id) or _404()
    values = {
        "name": c.name, "emoji": c.emoji, "color": c.color, "type": c.type.value,
        "parent_id": str(c.parent_id or ""), "archived": c.archived,
    }
    return _category_page(request, db, c, values, {})


@router.post("/categories/new")
@router.post("/categories/{category_id:int}")
async def category_save(request: Request, category_id: int | None = None, db: Session = Depends(get_db)):
    category = db.get(Category, category_id) or _404() if category_id else None
    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "emoji": str(form.get("emoji", "")).strip(),
        "color": str(form.get("color", "")),
        "type": str(form.get("type", "")),
        "parent_id": str(form.get("parent_id", "")),
        "archived": form.get("archived") == "on",
    }
    errors = {}
    if not values["name"]:
        errors["name"] = "Bitte einen Namen eingeben."
    if len(values["emoji"]) > 8:
        errors["emoji"] = "Bitte nur ein Emoji."
    if not COLOR_RE.match(values["color"]):
        errors["color"] = "Ungültige Farbe."

    parent = None
    if values["parent_id"]:
        parent = db.get(Category, int(values["parent_id"])) if values["parent_id"].isdigit() else None
        if parent is None or parent.parent_id is not None or (category and parent.id == category.id):
            errors["parent_id"] = "Ungültige Hauptkategorie."
        elif category and category.children:
            errors["parent_id"] = "Hat selbst Unterkategorien – kann keine Unterkategorie werden."
    if parent is not None:
        new_type = parent.type  # subcategories inherit the parent's type
    elif values["type"] in {t.value for t in CategoryType}:
        new_type = CategoryType(values["type"])
    else:
        new_type = None
        errors["type"] = "Bitte Einnahme oder Ausgabe wählen."
    if category and new_type and new_type != category.type and lookups.category_in_use(db, category):
        errors["type"] = "Wird verwendet – Einnahme/Ausgabe kann nicht mehr geändert werden."
    if errors:
        return _category_page(request, db, category, values, errors, 422)

    new_parent_id = parent.id if parent else None
    if category is None or category.parent_id != new_parent_id:
        siblings = Category.parent_id == new_parent_id if new_parent_id else Category.parent_id.is_(None)
        sort_order = _next_sort(db, Category.sort_order, siblings)
    else:
        sort_order = category.sort_order
    if category is None:
        category = Category()
        db.add(category)
    category.sort_order = sort_order
    category.name = values["name"]
    category.emoji = values["emoji"]
    category.color = values["color"]
    category.parent_id = new_parent_id
    category.type = new_type
    category.archived = values["archived"]
    for child in category.children:
        child.type = new_type
    db.commit()
    return _redirect("/settings/categories")


@router.post("/categories/{category_id:int}/delete")
def category_delete(category_id: int, request: Request, db: Session = Depends(get_db)):
    category = db.get(Category, category_id) or _404()
    error = None
    if lookups.category_in_use(db, category):
        error = "Wird verwendet – bitte archivieren statt löschen."
    elif category.children:
        error = "Bitte zuerst die Unterkategorien löschen."
    if error:
        values = {
            "name": category.name, "emoji": category.emoji, "color": category.color,
            "type": category.type.value, "parent_id": str(category.parent_id or ""),
            "archived": category.archived,
        }
        return _category_page(request, db, category, values, {"delete": error}, 409)
    db.delete(category)
    db.commit()
    return _redirect("/settings/categories")


# --- Tags ------------------------------------------------------------------------


def _tags_page(request, db, errors: dict | None = None, status=200):
    usage = dict(
        db.execute(select(entry_tags.c.tag_id, func.count()).group_by(entry_tags.c.tag_id)).all()
    )
    return render(request, "settings/tags.html", status, tags=lookups.tags(db), usage=usage,
                  errors=errors or {})


@router.get("/tags")
def tags(request: Request, db: Session = Depends(get_db)):
    return _tags_page(request, db)


@router.post("/tags/new")
@router.post("/tags/{tag_id:int}")
async def tag_save(request: Request, tag_id: int | None = None, db: Session = Depends(get_db)):
    tag = db.get(Tag, tag_id) or _404() if tag_id else None
    name = str((await request.form()).get("name", "")).strip()
    key = str(tag_id or "new")
    if not name:
        return _tags_page(request, db, {key: "Bitte einen Namen eingeben."}, 422)
    if db.scalar(select(Tag.id).where(Tag.name == name, Tag.id != tag_id)):
        return _tags_page(request, db, {key: "Dieses Tag gibt es schon."}, 422)
    if tag is None:
        db.add(Tag(name=name))
    else:
        tag.name = name
    db.commit()
    return _redirect("/settings/tags")


@router.post("/tags/{tag_id:int}/delete")
def tag_delete(tag_id: int, db: Session = Depends(get_db)):
    db.get(Tag, tag_id) or _404()
    db.execute(delete(Tag).where(Tag.id == tag_id))  # entry links cascade
    db.commit()
    return _redirect("/settings/tags")


def _404():
    raise HTTPException(404)
