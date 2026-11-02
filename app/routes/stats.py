from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import fmt
from app.db import get_db
from app.models import Category, CategoryType
from app.services import lookups, stats
from app.services.filters import EntryFilters
from app.templating import render

router = APIRouter(prefix="/stats")

MONTHS_SHORT = ["Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


class View:
    """Request-scoped helpers: filters and link building that keeps the filters."""

    def __init__(self, request: Request, db: Session):
        qp = request.query_params
        self.filters = EntryFilters.from_query(qp)
        self.filters.q = ""  # stats filter by account/tag only
        self.kind = CategoryType.income if qp.get("kind") == "income" else CategoryType.expense
        self.context = {
            "filters": self.filters,
            "kind": self.kind.value,
            "accounts": lookups.accounts(db, archived=True),
            "tags": lookups.tags(db),
            "url": self.url,
        }

    def filter_note(self) -> str:
        """Human-readable description of the active filters (for PDFs)."""
        accounts = [a.name for a in self.context["accounts"] if a.id in self.filters.account_ids]
        tags = [f"#{t.name}" for t in self.context["tags"] if t.id in self.filters.tag_ids]
        parts = ([f"Konten: {', '.join(accounts)}"] if accounts else []) + (
            [f"Tags: {', '.join(tags)}"] if tags else [])
        return " · ".join(parts)

    def url(self, path: str, **params) -> str:
        items = [(k, str(v)) for k, v in params.items() if v is not None] + self.filters.params()
        return f"{path}?{urlencode(items)}" if items else path


def parse_month(value: str | None) -> tuple[int, int]:
    try:
        y, m = (int(p) for p in (value or "").split("-"))
        if 1900 < y < 3000 and 1 <= m <= 12:
            return y, m
    except ValueError:
        pass
    t = fmt.today()
    return t.year, t.month


def parse_year(value: str | None) -> int:
    return int(value) if value and value.isdigit() and 1900 < int(value) < 3000 else fmt.today().year


def parse_months(value: str | None) -> int:
    """Kreditansicht period length: 1–36 complete months, default 6."""
    return int(value) if value and value.isdigit() and 1 <= int(value) <= 36 else 6


def _parse_day(value: str | None) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return fmt.today()


def month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def _donut(view: View, shares: list[stats.Share], link) -> dict:
    return {
        "labels": [f"{s.category.emoji} {s.category.name}" for s in shares],
        "values": [s.cents for s in shares],
        "colors": [s.category.color for s in shares],
        "links": [link(s.category) for s in shares],
    }


@router.get("")
def index(request: Request):
    return RedirectResponse("/stats/month" + (f"?{request.url.query}" if request.url.query else ""))


@router.get("/month")
def month(request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    y, m = parse_month(request.query_params.get("m"))
    start, end = stats.month_range(y, m)
    current = stats.totals(db, start, end, view.filters)
    prev_y, prev_m = stats.shift_month(y, m, -1)
    previous = stats.totals(db, *stats.month_range(prev_y, prev_m), view.filters)
    shares = stats.by_main_category(db, start, end, view.filters, view.kind)
    key = month_key(y, m)

    def drill(c: Category) -> str:
        return view.url(f"/stats/category/{c.id}", m=key)

    return render(
        request, "stats/month.html",
        view_name="month",
        title=f"{fmt.MONTHS[m - 1]} {y}",
        prev_url=view.url("/stats/month", m=month_key(prev_y, prev_m), kind=view.kind.value),
        next_url=view.url("/stats/month", m=month_key(*stats.shift_month(y, m, 1)), kind=view.kind.value),
        period={"m": key},
        totals=current,
        delta=current - previous,
        delta_label=f"ggü. {fmt.MONTHS[prev_m - 1]}",
        shares=shares,
        drill=drill,
        chart=_donut(view, shares, drill),
        kind_urls={k: view.url("/stats/month", m=key, kind=k) for k in ("expense", "income")},
        pdf_url=view.url("/export/month.pdf", m=key),
        **view.context,
    )


@router.get("/year")
def year(request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    y = parse_year(request.query_params.get("y"))
    months = stats.monthly_totals(db, y, view.filters)
    total = sum(months, stats.Totals())
    start, end = date(y, 1, 1), date(y + 1, 1, 1)
    shares = stats.by_main_category(db, start, end, view.filters, view.kind)

    def drill(c: Category) -> str:
        return view.url(f"/stats/category/{c.id}", y=y)

    return render(
        request, "stats/year.html",
        view_name="year",
        title=str(y),
        prev_url=view.url("/stats/year", y=y - 1, kind=view.kind.value),
        next_url=view.url("/stats/year", y=y + 1, kind=view.kind.value),
        period={"y": y},
        totals=total,
        months=months,
        month_names=MONTHS_SHORT,
        month_urls=[view.url("/stats/month", m=month_key(y, i)) for i in range(1, 13)],
        bars={
            "labels": MONTHS_SHORT,
            "einnahmen": [t.einnahmen for t in months],
            "ausgaben": [t.ausgaben for t in months],
            "gespart": [t.gespart for t in months],
            "links": [view.url("/stats/month", m=month_key(y, i)) for i in range(1, 13)],
        },
        shares=shares,
        drill=drill,
        chart=_donut(view, shares, drill),
        kind_urls={k: view.url("/stats/year", y=y, kind=k) for k in ("expense", "income")},
        pdf_url=view.url("/export/year.pdf", y=y),
        **view.context,
    )


@router.get("/day")
def day(request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    d = _parse_day(request.query_params.get("d"))
    end = d + timedelta(days=1)
    return render(
        request, "stats/day.html",
        view_name="day",
        title=fmt.day_heading(d),
        prev_url=view.url("/stats/day", d=(d - timedelta(days=1)).isoformat()),
        next_url=view.url("/stats/day", d=end.isoformat()),
        period={"d": d.isoformat()},
        day=d,
        totals=stats.totals(db, d, end, view.filters),
        entries=stats.entries(db, d, end, view.filters),
        **view.context,
    )


@router.get("/category/{category_id:int}")
def category(category_id: int, request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(404)
    main = cat.main
    qp = request.query_params
    if "y" in qp:
        y = parse_year(qp.get("y"))
        start, end = date(y, 1, 1), date(y + 1, 1, 1)
        period, label, back_url = {"y": y}, str(y), view.url("/stats/year", y=y, kind=main.type.value)
    else:
        y, m = parse_month(qp.get("m"))
        start, end = stats.month_range(y, m)
        key = month_key(y, m)
        period, label = {"m": key}, f"{fmt.MONTHS[m - 1]} {y}"
        back_url = view.url("/stats/month", m=key, kind=main.type.value)

    subs = stats.by_subcategory(db, main, start, end, view.filters)
    ids = [main.id, *(c.id for c in main.children)]
    return render(
        request, "stats/category.html",
        main=main,
        label=label,
        back_url=back_url,
        period=period,
        shares=subs,
        total=sum(s.cents for s in subs),
        entries=stats.entries(db, start, end, view.filters, ids),
        **view.context,
    )


LOAN_CHOICES = [3, 6, 12, 24]


@router.get("/loan")
def loan(request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    n = parse_months(request.query_params.get("n"))
    start, end = stats.loan_period(fmt.today(), n)
    return render(
        request, "stats/loan.html",
        view_name="loan",
        title="Kreditansicht",
        period={"n": n},
        n=n,
        choices=sorted({*LOAN_CHOICES, n}),
        period_label=f"{fmt.month_label(start)} – {fmt.month_label(end - timedelta(days=1))}",
        statement=stats.statement(db, start, end, view.filters),
        pdf_url=view.url("/export/loan.pdf", n=n),
        **view.context,
    )
