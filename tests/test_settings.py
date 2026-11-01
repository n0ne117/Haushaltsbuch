from datetime import date

from sqlalchemy import select

from app.models import Account, Category, Entry, EntryType, Tag
from app.services.entries import EntryData, create_entry


def _use(db, seed, account="Bargeld", category="Supermarkt"):
    return create_entry(db, EntryData(EntryType.expense, date(2026, 1, 1), 100, seed.account(account).id,
                                      category_id=seed.category(category).id,
                                      tag_ids=[seed.tag("Kreditkarte").id]))


# --- Accounts --------------------------------------------------------------------


def test_create_account(client, db):
    r = client.post("/settings/accounts/new", data={"name": "Sparkonto", "owner": "", "kind": "savings"},
                    follow_redirects=False)
    assert r.status_code == 303
    acc = db.scalars(select(Account).where(Account.name == "Sparkonto")).one()
    assert acc.kind.value == "savings" and acc.owner is None and acc.sort_order == 4


def test_account_name_unique(client, seed):
    r = client.post("/settings/accounts/new", data={"name": "Bargeld", "kind": "cash"})
    assert r.status_code == 422 and "gibt es schon" in r.text


def test_used_account_cannot_be_deleted_only_archived(client, db, seed):
    _use(db, seed)
    acc = seed.account("Bargeld")
    r = client.post(f"/settings/accounts/{acc.id}/delete")
    assert r.status_code == 409 and "archivieren" in r.text
    client.post(f"/settings/accounts/{acc.id}", data={"name": "Bargeld", "kind": "cash", "archived": "on"})
    db.expunge_all()
    assert db.get(Account, acc.id).archived
    # Archived accounts are hidden from the quick-add picker but still listed in settings.
    assert f'name="account_id" value="{acc.id}"' not in client.get("/").text
    assert "Bargeld" in client.get("/settings/accounts").text
    # …and remain selectable when editing an entry that uses them.
    entry = db.scalars(select(Entry)).one()
    assert f'name="account_id" value="{acc.id}"' in client.get(f"/entries/{entry.id}").text


def test_unused_account_can_be_deleted(client, db, seed):
    acc = seed.account("Bargeld")
    assert client.post(f"/settings/accounts/{acc.id}/delete", follow_redirects=False).status_code == 303
    db.expunge_all()
    assert db.get(Account, acc.id) is None


def test_reorder_accounts(client, db, seed):
    ids = [seed.account(n).id for n in ["Depot", "Bargeld", "Girokonto Alex", "Girokonto Partnerin"]]
    assert client.post("/settings/accounts/reorder", data={"ids": ids}).status_code == 204
    db.expunge_all()
    names = db.scalars(select(Account.name).order_by(Account.sort_order)).all()
    assert names == ["Depot", "Bargeld", "Girokonto Alex", "Girokonto Partnerin"]


# --- Categories ------------------------------------------------------------------


def _cat_form(**kw):
    base = {"name": "Neu", "emoji": "✨", "color": "#123456", "type": "expense", "parent_id": ""}
    base.update(kw)
    return base


def test_create_subcategory_inherits_type(client, db, seed):
    gehalt = seed.category("Gehalt")
    r = client.post("/settings/categories/new", data=_cat_form(name="Bonus", type="expense", parent_id=gehalt.id),
                    follow_redirects=False)
    assert r.status_code == 303
    bonus = seed.category("Bonus")
    assert bonus.parent_id == gehalt.id and bonus.type.value == "income"


def test_max_depth_two(client, seed):
    sub = seed.category("Miete")
    r = client.post("/settings/categories/new", data=_cat_form(parent_id=sub.id))
    assert r.status_code == 422 and "Ungültige Hauptkategorie" in r.text


def test_main_with_children_cannot_become_sub(client, seed):
    wohnen, abos = seed.category("Wohnen"), seed.category("Abos")
    r = client.post(f"/settings/categories/{wohnen.id}", data=_cat_form(name="Wohnen", parent_id=abos.id))
    assert r.status_code == 422 and "Unterkategorien" in r.text


def test_type_change_blocked_when_used(client, db, seed):
    _use(db, seed, category="Supermarkt")
    lm = seed.category("Lebensmittel")
    r = client.post(f"/settings/categories/{lm.id}", data=_cat_form(name="Lebensmittel", type="income"))
    assert r.status_code == 422 and "Wird verwendet" in r.text


def test_type_change_cascades_to_children_when_unused(client, db, seed):
    mob = seed.category("Mobilität")
    r = client.post(f"/settings/categories/{mob.id}", data=_cat_form(name="Mobilität", type="income"),
                    follow_redirects=False)
    assert r.status_code == 303
    db.expunge_all()
    assert {c.type.value for c in [db.get(Category, mob.id), *db.get(Category, mob.id).children]} == {"income"}


def test_used_category_cannot_be_deleted(client, db, seed):
    _use(db, seed, category="Supermarkt")
    sub = seed.category("Supermarkt")
    assert client.post(f"/settings/categories/{sub.id}/delete").status_code == 409
    # The parent counts as used too.
    assert client.post(f"/settings/categories/{seed.category('Lebensmittel').id}/delete").status_code == 409


def test_unused_leaf_category_can_be_deleted(client, db, seed):
    abos = seed.category("Abos")
    assert client.post(f"/settings/categories/{abos.id}/delete", follow_redirects=False).status_code == 303
    db.expunge_all()
    assert db.get(Category, abos.id) is None


def test_archived_category_hidden_from_quick_add(client, db, seed):
    abos = seed.category("Abos")
    client.post(f"/settings/categories/{abos.id}", data=_cat_form(name="Abos", archived="on"))
    assert f'name="category_id" value="{abos.id}"' not in client.get("/").text


# --- Tags ------------------------------------------------------------------------


def test_tags_crud(client, db, seed):
    assert client.post("/settings/tags/new", data={"name": "Urlaub 2027"}, follow_redirects=False).status_code == 303
    assert client.post("/settings/tags/new", data={"name": "Urlaub 2027"}).status_code == 422
    tag = seed.tag("Urlaub 2027")
    client.post(f"/settings/tags/{tag.id}", data={"name": "Urlaub 2028"})
    db.expunge_all()
    assert db.get(Tag, tag.id).name == "Urlaub 2028"


def test_deleting_tag_removes_it_from_entries(client, db, seed):
    entry = _use(db, seed)
    kk = seed.tag("Kreditkarte")
    assert client.post(f"/settings/tags/{kk.id}/delete", follow_redirects=False).status_code == 303
    db.expunge_all()
    assert db.get(Entry, entry.id).tags == []
