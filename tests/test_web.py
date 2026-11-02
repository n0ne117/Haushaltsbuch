import re
from datetime import date, timedelta

from sqlalchemy import func, select

from app import fmt
from app.models import Account, Category, Entry, EntryType
from app.services.entries import EntryData, create_entry

HX = {"HX-Request": "true"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seed_data(db):
    assert db.scalar(select(func.count()).select_from(Account)) == 4
    mains = db.scalars(select(Category.name).where(Category.parent_id.is_(None), Category.type == "income")).all()
    assert mains == ["Gehalt", "Kapitalerträge", "Sonstiges"]
    depot = db.scalars(select(Account).where(Account.name == "Depot")).one()
    assert depot.kind.value == "savings"


def test_pages_render(client, seed):
    for url in ["/", "/entries", "/settings", "/settings/accounts", "/settings/categories",
                "/settings/tags", "/help", "/stats", "/settings/accounts/new",
                f"/settings/categories/new?parent={seed.category('Wohnen').id}"]:
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Haushaltsbuch" in r.text


def test_quick_add_htmx(client, db, seed):
    acc = seed.account("Bargeld").id
    r = client.post("/entries", headers=HX, data={
        "type": "expense", "amount": "12,50", "account_id": acc,
        "category_id": seed.category("Markt/Bäcker").id, "date": "", "note": "",
    })
    assert r.status_code == 200
    assert "Gespeichert" in r.text and "Rückgängig" in r.text
    assert r.cookies.get("last_account") == str(acc)
    entry = db.scalars(select(Entry)).one()
    assert entry.amount_cents == 1250 and entry.date == fmt.today()

    # The fresh form pre-selects the remembered account.
    assert re.search(rf'name="account_id" value="{acc}"\s+checked', client.get("/").text)


def test_quick_add_ignores_fields_of_other_types(client, db, seed):
    # A transfer submitted with a leftover category (e.g. JS disabled) is still booked as transfer.
    r = client.post("/entries", headers=HX, data={
        "type": "transfer", "amount": "100", "account_id": seed.account("Girokonto Alex").id,
        "to_account_id": seed.account("Bargeld").id, "category_id": seed.category("Supermarkt").id,
    })
    assert r.status_code == 200
    e = db.scalars(select(Entry)).one()
    assert e.type == EntryType.transfer and e.category_id is None


def test_quick_add_validation_error(client, db, seed):
    r = client.post("/entries", headers=HX, data={
        "type": "expense", "amount": "abc", "account_id": seed.account("Bargeld").id,
    })
    assert r.status_code == 422
    assert "Ungültiger Betrag" in r.text
    assert db.scalar(select(func.count()).select_from(Entry)) == 0


def test_quick_add_without_htmx_redirects(client, seed):
    r = client.post("/entries", follow_redirects=False, data={
        "type": "income", "amount": "3000", "account_id": seed.account("Girokonto Alex").id,
        "category_id": seed.category("Gehalt").id,
    })
    assert r.status_code == 303


def test_undo(client, db, seed):
    e = create_entry(db, EntryData(EntryType.expense, date.today(), 100, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id))
    r = client.post(f"/entries/{e.id}/undo", headers=HX)
    assert "Rückgängig gemacht" in r.text
    db.expunge_all()
    assert db.get(Entry, e.id) is None


def test_undo_window_expired(client, db, seed):
    e = create_entry(db, EntryData(EntryType.expense, date.today(), 100, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id))
    e.created_at -= timedelta(minutes=10)
    db.commit()
    r = client.post(f"/entries/{e.id}/undo", headers=HX)
    assert "Zu spät" in r.text
    assert db.get(Entry, e.id) is not None


def _make_entries(db, seed, n):
    acc = seed.account("Bargeld").id
    cat = seed.category("Supermarkt").id
    for i in range(n):
        db.add(Entry(type=EntryType.expense, date=date(2026, 1, 1) + timedelta(days=i // 3),
                     amount_cents=100 + i, account_id=acc, category_id=cat, note=f"Nr {i}"))
    db.commit()


def test_list_pagination_and_day_headers(client, db, seed):
    _make_entries(db, seed, 60)
    first = client.get("/entries").text
    assert first.count('class="row"') == 50
    assert "/entries/rows?offset=50" in first.replace("&amp;", "&")
    # 60 entries, 3 per day → 20 days; first page shows 50 → days 20..4 (17 headers, last one partial)
    assert first.count('class="day"') == 17
    prev = date(2026, 1, 1) + timedelta(days=(59 - 49) // 3)
    nxt = client.get(f"/entries/rows?offset=50&prev={prev.isoformat()}").text
    assert nxt.count('class="row"') == 10
    assert nxt.count('class="day"') == 3  # no repeated heading for the partial day
    assert "sentinel" not in nxt


def test_list_search_and_filters(client, db, seed):
    _make_entries(db, seed, 5)
    create_entry(db, EntryData(EntryType.transfer, date(2026, 2, 1), 5000, seed.account("Girokonto Alex").id,
                               to_account_id=seed.account("Depot").id, note="Sparplan"))
    assert client.get("/entries/rows?q=Nr 3").text.count('class="row"') == 1
    assert client.get("/entries/rows?q=nr").text.count('class="row"') == 5  # case-insensitive
    depot = seed.account("Depot").id
    assert client.get(f"/entries/rows?account={depot}").text.count('class="row"') == 1
    assert "Keine Buchungen" in client.get("/entries/rows?q=xyz").text


def test_edit_and_delete_entry(client, db, seed):
    e = create_entry(db, EntryData(EntryType.expense, date(2026, 3, 1), 999, seed.account("Bargeld").id,
                                   category_id=seed.category("Supermarkt").id))
    page = client.get(f"/entries/{e.id}")
    assert 'value="9,99"' in page.text
    r = client.post(f"/entries/{e.id}", follow_redirects=False, data={
        "type": "expense", "amount": "10,49", "account_id": seed.account("Bargeld").id,
        "category_id": seed.category("Tanken").id, "date": "2026-03-02", "note": "Diesel",
    })
    assert r.status_code == 303
    db.expunge_all()
    e = db.get(Entry, e.id)
    assert (e.amount_cents, e.category.name, e.date, e.note) == (1049, "Tanken", date(2026, 3, 2), "Diesel")
    assert client.post(f"/entries/{e.id}/delete", follow_redirects=False).status_code == 303
    db.expunge_all()
    assert db.get(Entry, e.id) is None
    assert client.get(f"/entries/{e.id}").status_code == 404


def test_pwa_manifest_and_service_worker(client):
    page = client.get("/").text
    manifest_url = re.search(r'rel="manifest" href="([^"]+)"', page).group(1)
    r = client.get(manifest_url)
    assert r.headers["content-type"].startswith("application/manifest+json")
    manifest = r.json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"

    sw = client.get("/sw.js")
    assert sw.headers["content-type"].startswith("text/javascript")
    assert sw.headers["cache-control"] == "no-cache"
    assert "/static/app.css?v=" in sw.text and "/static/vendor/chart.umd.min.js?v=" in sw.text
    assert 'startsWith("/static/")' in sw.text  # pages and writes are never cached
