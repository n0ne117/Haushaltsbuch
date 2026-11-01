import hashlib
from functools import cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import fmt
from app.models import AccountKind, EntryType

STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@cache
def static_url(path: str) -> str:
    """/static/<path>?v=<content hash>, so browsers pick up changed assets after an update."""
    digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    return f"/static/{path}?v={digest}"


templates.env.filters.update(
    money=fmt.money,
    date_de=fmt.date_de,
    day_heading=fmt.day_heading,
    amount_input=fmt.amount_input,
)
templates.env.globals.update(
    static=static_url,
    EntryType=EntryType,
    TYPE_LABELS={
        EntryType.expense: "Ausgabe",
        EntryType.income: "Einnahme",
        EntryType.transfer: "Umbuchung",
    },
    KIND_LABELS={
        AccountKind.checking: "Girokonto",
        AccountKind.cash: "Bargeld",
        AccountKind.savings: "Sparen / Depot",
    },
)


def render(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
