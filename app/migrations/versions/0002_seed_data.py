"""seed data (spec §10) – runs once; everything is editable afterwards

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ACCOUNTS = [
    # name, owner, kind
    ("Girokonto Alex", "Alex", "checking"),
    ("Girokonto Partnerin", "Partnerin", "checking"),
    ("Bargeld", "Gemeinsam", "cash"),
    ("Depot", "Gemeinsam", "savings"),
]

TAGS = ["Kreditkarte"]

# type, name, emoji, color, [(sub name, sub emoji), ...]
CATEGORIES = [
    ("income", "Gehalt", "💼", "#2e7d32", []),
    ("income", "Kapitalerträge", "📈", "#00897b", []),
    ("income", "Sonstiges", "➕", "#7cb342", []),
    ("expense", "Wohnen", "🏠", "#5c6bc0", [
        ("Miete", "🔑"), ("Betriebskosten", "🧾"), ("Strom", "⚡"), ("Internet/Handy", "📶"),
    ]),
    ("expense", "Lebensmittel", "🛒", "#43a047", [("Supermarkt", "🛒"), ("Markt/Bäcker", "🥖")]),
    ("expense", "Mobilität", "🚌", "#1e88e5", [("Öffis", "🚋"), ("Tanken", "⛽"), ("Auto", "🚗")]),
    ("expense", "Versicherungen", "🛡️", "#6d4c41", []),
    ("expense", "Kind", "🧒", "#f9a825", [("Schule", "🎒"), ("Freizeit", "⚽"), ("Kleidung", "👟")]),
    ("expense", "Gesundheit", "💊", "#e53935", []),
    ("expense", "Freizeit", "🎉", "#8e24aa", [("Essen gehen", "🍽️"), ("Hobbys", "🎨"), ("Urlaub", "🏖️")]),
    ("expense", "Abos", "🔁", "#00acc1", []),
    ("expense", "Haushalt & Kleidung", "👕", "#ec407a", []),
    ("expense", "Gebühren", "🏦", "#546e7a", []),
    ("expense", "Sonstiges", "📦", "#9e9e9e", []),
]


def upgrade() -> None:
    conn = op.get_bind()
    accounts = sa.table(
        "accounts",
        sa.column("name"), sa.column("owner"), sa.column("kind"),
        sa.column("archived"), sa.column("sort_order"),
    )
    tags = sa.table("tags", sa.column("name"))
    categories = sa.table(
        "categories",
        sa.column("id"), sa.column("name"), sa.column("parent_id"), sa.column("type"),
        sa.column("emoji"), sa.column("color"), sa.column("archived"), sa.column("sort_order"),
    )

    conn.execute(accounts.insert(), [
        {"name": n, "owner": o, "kind": k, "archived": False, "sort_order": i}
        for i, (n, o, k) in enumerate(ACCOUNTS)
    ])
    conn.execute(tags.insert(), [{"name": n} for n in TAGS])

    for i, (typ, name, emoji, color, subs) in enumerate(CATEGORIES):
        main_id = conn.execute(
            categories.insert().values(
                name=name, parent_id=None, type=typ, emoji=emoji, color=color,
                archived=False, sort_order=i,
            ).returning(categories.c.id)
        ).scalar_one()
        for j, (sub_name, sub_emoji) in enumerate(subs):
            conn.execute(
                categories.insert().values(
                    name=sub_name, parent_id=main_id, type=typ, emoji=sub_emoji, color=color,
                    archived=False, sort_order=j,
                )
            )


def downgrade() -> None:
    op.execute("DELETE FROM entry_tags")
    op.execute("DELETE FROM entries")
    op.execute("DELETE FROM categories WHERE parent_id IS NOT NULL")
    op.execute("DELETE FROM categories")
    op.execute("DELETE FROM tags")
    op.execute("DELETE FROM accounts")
