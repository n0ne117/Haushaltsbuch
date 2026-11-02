from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import fmt
from app.config import TZ
from app.db import get_db
from app.pdf import render_pdf
from app.routes.stats import View, month_key, parse_month, parse_months, parse_year
from app.services import backup, stats
from app.services.export import entries_csv
from app.templating import render

router = APIRouter()


def _download(content: bytes, filename: str, media_type: str, inline: bool = False) -> Response:
    disposition = "inline" if inline else "attachment"
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return default


@router.get("/settings/export")
def export_page(request: Request):
    today = fmt.today()
    return render(
        request, "settings/export.html",
        csv_from=date(today.year, 1, 1).isoformat(),
        csv_to=today.isoformat(),
        month=month_key(today.year, today.month),
        year=today.year,
        backup=backup.status(),
    )


@router.get("/export/entries.csv")
def export_csv(request: Request, db: Session = Depends(get_db)):
    today = fmt.today()
    start = _parse_date(request.query_params.get("from"), date(today.year, 1, 1))
    end = _parse_date(request.query_params.get("to"), today)
    if end < start:
        start, end = end, start
    return _download(entries_csv(db, start, end), f"haushaltsbuch_{start}_{end}.csv", "text/csv; charset=utf-8")


def _statement_pdf(request: Request, db: Session, title: str, start: date, end: date, filename: str,
                   months: list | None = None) -> Response:
    view = View(request, db)
    pdf = render_pdf(
        "pdf/statement.html",
        title=title,
        filter_note=view.filter_note(),
        statement=stats.statement(db, start, end, view.filters),
        months=months,
        last_day=end - timedelta(days=1),
        entries=stats.entries(db, start, end, view.filters)[::-1],  # oldest first
        generated=datetime.now(TZ),
    )
    return _download(pdf, filename, "application/pdf", inline=True)


@router.get("/export/month.pdf")
def month_pdf(request: Request, db: Session = Depends(get_db)):
    y, m = parse_month(request.query_params.get("m"))
    start, end = stats.month_range(y, m)
    return _statement_pdf(request, db, f"Monatsauszug {fmt.MONTHS[m - 1]} {y}", start, end,
                          f"haushaltsbuch_{month_key(y, m)}.pdf")


@router.get("/export/year.pdf")
def year_pdf(request: Request, db: Session = Depends(get_db)):
    y = parse_year(request.query_params.get("y"))
    view = View(request, db)
    months = list(zip(fmt.MONTHS, stats.monthly_totals(db, y, view.filters), strict=True))
    return _statement_pdf(request, db, f"Jahresauszug {y}", date(y, 1, 1), date(y + 1, 1, 1),
                          f"haushaltsbuch_{y}.pdf", months)


@router.get("/export/loan.pdf")
def loan_pdf(request: Request, db: Session = Depends(get_db)):
    view = View(request, db)
    n = parse_months(request.query_params.get("n"))
    start, end = stats.loan_period(fmt.today(), n)
    last = end - timedelta(days=1)
    pdf = render_pdf(
        "pdf/loan.html",
        n=n,
        period_label=f"{fmt.month_label(start)} – {fmt.month_label(last)}",
        filter_note=view.filter_note(),
        statement=stats.statement(db, start, end, view.filters),
        generated=datetime.now(TZ),
    )
    return _download(pdf, f"haushaltsbuch_kreditansicht_{month_key(start.year, start.month)}"
                          f"_{month_key(last.year, last.month)}.pdf", "application/pdf", inline=True)
