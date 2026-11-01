"""Account/tag/search filters shared by the entry list and statistics."""

from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import joinedload, selectinload
from starlette.datastructures import QueryParams

from app.models import Category, Entry, Tag


@dataclass
class EntryFilters:
    account_ids: list[int] = field(default_factory=list)
    tag_ids: list[int] = field(default_factory=list)
    q: str = ""

    @classmethod
    def from_query(cls, qp: QueryParams) -> "EntryFilters":
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

    def conditions(self) -> list[ColumnElement[bool]]:
        """Account filter matches either side of a transfer; tag filter matches any selected tag."""
        conds: list[ColumnElement[bool]] = []
        if self.account_ids:
            conds.append(or_(Entry.account_id.in_(self.account_ids), Entry.to_account_id.in_(self.account_ids)))
        if self.tag_ids:
            conds.append(Entry.tags.any(Tag.id.in_(self.tag_ids)))
        if self.q:
            conds.append(Entry.note.contains(self.q, autoescape=True))
        return conds


ENTRY_LOAD_OPTIONS = (
    joinedload(Entry.account),
    joinedload(Entry.to_account),
    joinedload(Entry.category).joinedload(Category.parent),
    selectinload(Entry.tags),
)
