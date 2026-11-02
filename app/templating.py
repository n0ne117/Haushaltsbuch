import hashlib
from functools import cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import fmt
from app.models import AccountKind, Entry, EntryType

STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@cache
def static_url(path: str) -> str:
    """/static/<path>?v=<content hash>, so browsers pick up changed assets after an update."""
    digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    return f"/static/{path}?v={digest}"


def entry_summary(e: Entry) -> str:
    """'−23,40 € · 🛒 Supermarkt' or '200,00 € · Girokonto → Depot' (for toasts)."""
    sign = {EntryType.expense: "−", EntryType.income: "+"}.get(e.type, "")
    where = f"{e.category.emoji} {e.category.name}" if e.category else f"{e.account.name} → {e.to_account.name}"
    return f"{fmt.money(e.amount_cents, sign)} · {where}"


def static_assets() -> list[str]:
    """Versioned URLs of every static file (precached by the service worker)."""
    return sorted(static_url(p.relative_to(STATIC_DIR).as_posix())
                  for p in STATIC_DIR.rglob("*") if p.is_file())


def assets_version() -> str:
    return hashlib.sha256("".join(static_assets()).encode()).hexdigest()[:12]


templates.env.filters.update(
    money=fmt.money,
    money_signed=fmt.money_signed,
    date_de=fmt.date_de,
    day_heading=fmt.day_heading,
    amount_input=fmt.amount_input,
    percent=fmt.percent,
    per_month=fmt.per_month,
    month_label=fmt.month_label,
)
templates.env.globals.update(
    static=static_url,
    entry_summary=entry_summary,
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
