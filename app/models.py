from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    MetaData,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _enum(cls: type[StrEnum]) -> Enum:
    return Enum(
        cls,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
        name=cls.__name__.lower(),
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountKind(StrEnum):
    checking = "checking"
    cash = "cash"
    savings = "savings"


class CategoryType(StrEnum):
    income = "income"
    expense = "expense"


class EntryType(StrEnum):
    income = "income"
    expense = "expense"
    transfer = "transfer"


class Frequency(StrEnum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class OccurrenceStatus(StrEnum):
    pending = "pending"
    booked = "booked"
    skipped = "skipped"


entry_tags = Table(
    "entry_tags",
    Base.metadata,
    Column("entry_id", ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

recurring_tags = Table(
    "recurring_tags",
    Base.metadata,
    Column("recurring_id", ForeignKey("recurring_templates.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    owner: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[AccountKind] = mapped_column(_enum(AccountKind), default=AccountKind.checking)
    archived: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    type: Mapped[CategoryType] = mapped_column(_enum(CategoryType))
    emoji: Mapped[str] = mapped_column(String(16), default="")
    color: Mapped[str] = mapped_column(String(7), default="#888888")
    archived: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", order_by="Category.sort_order"
    )

    @property
    def main(self) -> "Category":
        return self.parent or self

    @property
    def label(self) -> str:
        return f"{self.parent.name} › {self.name}" if self.parent else self.name


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class RecurringTemplate(Base):
    __tablename__ = "recurring_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[EntryType] = mapped_column(_enum(EntryType))
    amount_cents: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    to_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[Frequency] = mapped_column(_enum(Frequency))
    # Day of month (1–31, clamped to month end) or weekday (0 = Monday) for weekly.
    day: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)

    tags: Mapped[list[Tag]] = relationship(secondary=recurring_tags, order_by=Tag.name)

    __table_args__ = (CheckConstraint("amount_cents > 0", name="amount_positive"),)


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[EntryType] = mapped_column(_enum(EntryType))
    date: Mapped[date] = mapped_column(Date, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    to_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    recurring_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_templates.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    account: Mapped[Account] = relationship(foreign_keys=[account_id])
    to_account: Mapped[Account | None] = relationship(foreign_keys=[to_account_id])
    category: Mapped[Category | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=entry_tags, order_by=Tag.name)

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "(type = 'transfer' AND to_account_id IS NOT NULL AND category_id IS NULL"
            " AND to_account_id != account_id)"
            " OR (type != 'transfer' AND to_account_id IS NULL AND category_id IS NOT NULL)",
            name="type_rules",
        ),
    )


class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_id: Mapped[int] = mapped_column(ForeignKey("recurring_templates.id", ondelete="CASCADE"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[OccurrenceStatus] = mapped_column(
        _enum(OccurrenceStatus), default=OccurrenceStatus.pending
    )
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id", ondelete="SET NULL"))

    __table_args__ = (UniqueConstraint("recurring_id", "due_date"),)
