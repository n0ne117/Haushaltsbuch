"""Statistics (spec §7.1).

Einnahmen = income entries, Ausgaben = expense entries.
Gespart   = transfers from non-savings into savings accounts
            − transfers from savings back into non-savings accounts.
Saldo     = Einnahmen − Ausgaben − Gespart.
Transfers that stay on one side (checking ↔ cash, Depot ↔ Sparkonto) count nowhere.
Only booked entries exist in `entries`, so pending recurring occurrences never count.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session, aliased

from app.models import Account, AccountKind, Category, CategoryType, Entry, EntryType
from app.services.filters import ENTRY_LOAD_OPTIONS, EntryFilters


@dataclass
class Totals:
    einnahmen: int = 0
    ausgaben: int = 0
    gespart: int = 0

    @property
    def saldo(self) -> int:
        return self.einnahmen - self.ausgaben - self.gespart

    def __add__(self, other: "Totals") -> "Totals":
        return Totals(self.einnahmen + other.einnahmen, self.ausgaben + other.ausgaben,
                      self.gespart + other.gespart)

    def __sub__(self, other: "Totals") -> "Totals":
        return Totals(self.einnahmen - other.einnahmen, self.ausgaben - other.ausgaben,
                      self.gespart - other.gespart)


@dataclass
class Share:
    category: Category
    cents: int
    pct: float


def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + month // 12, month % 12 + 1, 1)
    return start, end


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    m = year * 12 + (month - 1) + delta
    return m // 12, m % 12 + 1


def _period(start: date, end: date, f: EntryFilters):
    return [Entry.date >= start, Entry.date < end, *f.conditions()]


def totals(db: Session, start: date, end: date, f: EntryFilters) -> Totals:
    """Totals for [start, end)."""
    conds = _period(start, end, f)
    by_type = dict(
        db.execute(
            select(Entry.type, func.sum(Entry.amount_cents))
            .where(Entry.type.in_([EntryType.income, EntryType.expense]), *conds)
            .group_by(Entry.type)
        ).all()
    )
    src, dst = aliased(Account), aliased(Account)
    savings = AccountKind.savings
    gespart = db.scalar(
        select(
            func.sum(
                case(
                    (and_(dst.kind == savings, src.kind != savings), Entry.amount_cents),
                    (and_(src.kind == savings, dst.kind != savings), -Entry.amount_cents),
                    else_=0,
                )
            )
        )
        .select_from(Entry)
        .join(src, Entry.account_id == src.id)
        .join(dst, Entry.to_account_id == dst.id)
        .where(Entry.type == EntryType.transfer, *conds)
    )
    return Totals(by_type.get(EntryType.income, 0), by_type.get(EntryType.expense, 0), gespart or 0)


def monthly_totals(db: Session, year: int, f: EntryFilters) -> list[Totals]:
    return [totals(db, *month_range(year, m), f) for m in range(1, 13)]


def _shares(db: Session, group_col, start: date, end: date, f: EntryFilters, *where) -> list[Share]:
    rows = db.execute(
        select(group_col.label("cat_id"), func.sum(Entry.amount_cents).label("cents"))
        .join(Category, Entry.category_id == Category.id)
        .where(*_period(start, end, f), *where)
        .group_by("cat_id")
        .order_by(desc("cents"))
    ).all()
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.id.in_([r.cat_id for r in rows])))}
    total = sum(r.cents for r in rows) or 1
    return [Share(cats[r.cat_id], r.cents, r.cents * 100 / total) for r in rows]


def by_main_category(db: Session, start: date, end: date, f: EntryFilters, kind: CategoryType) -> list[Share]:
    main_id = func.coalesce(Category.parent_id, Category.id)
    return _shares(db, main_id, start, end, f, Entry.type == EntryType(kind.value))


def by_subcategory(db: Session, main: Category, start: date, end: date, f: EntryFilters) -> list[Share]:
    """Shares per subcategory; entries booked on the main category itself appear as the main."""
    ids = [main.id, *(c.id for c in main.children)]
    return _shares(db, Entry.category_id, start, end, f, Entry.category_id.in_(ids))


def entries(db: Session, start: date, end: date, f: EntryFilters, category_ids: list[int] | None = None
            ) -> list[Entry]:
    stmt = select(Entry).options(*ENTRY_LOAD_OPTIONS).where(*_period(start, end, f))
    if category_ids is not None:
        stmt = stmt.where(Entry.category_id.in_(category_ids))
    return list(db.scalars(stmt.order_by(Entry.date.desc(), Entry.id.desc())).unique())


def next_day(d: date) -> date:
    return d + timedelta(days=1)
