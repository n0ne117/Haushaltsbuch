"""Picker data: active accounts, category trees and tags, sorted for display."""

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Account, Category, CategoryType, Entry, RecurringTemplate, Tag


def accounts(db: Session, archived: bool = False) -> list[Account]:
    stmt = select(Account).order_by(Account.sort_order, Account.name)
    if not archived:
        stmt = stmt.where(Account.archived.is_(False))
    return list(db.scalars(stmt))


def category_tree(
    db: Session, type: CategoryType | None = None, include_id: int | None = None, archived: bool = False
) -> list[tuple[Category, list[Category]]]:
    """[(main, [subs])] in sort order. Archived ones are hidden unless `archived` or `include_id`."""
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None))
        .options(selectinload(Category.children))
        .order_by(Category.sort_order, Category.name)
    )
    if type is not None:
        stmt = stmt.where(Category.type == type)

    def keep(c: Category) -> bool:
        return archived or not c.archived or c.id == include_id

    tree = []
    for main in db.scalars(stmt):
        subs = [c for c in main.children if keep(c)]
        if keep(main) or subs:
            tree.append((main, subs))
    return tree


def tags(db: Session) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.name)))


def account_in_use(db: Session, account_id: int) -> bool:
    return db.scalar(
        select(
            exists().where(or_(Entry.account_id == account_id, Entry.to_account_id == account_id))
        )
    ) or db.scalar(
        select(
            exists().where(
                or_(
                    RecurringTemplate.account_id == account_id,
                    RecurringTemplate.to_account_id == account_id,
                )
            )
        )
    )


def category_in_use(db: Session, category: Category) -> bool:
    """True if the category or any of its subcategories is referenced."""
    ids = [category.id, *(c.id for c in category.children)]
    return db.scalar(select(exists().where(Entry.category_id.in_(ids)))) or db.scalar(
        select(exists().where(RecurringTemplate.category_id.in_(ids)))
    )
