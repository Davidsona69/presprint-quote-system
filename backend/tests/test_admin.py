"""
Admin access control, history and export.

The auth tests are the point. Customer names, phone numbers and order values
live behind these routes, and the previous guard fell open whenever
ENVIRONMENT was "development" — which is exactly what docker-compose sets. So
these assert the closed states as hard as the open one.
"""
import csv
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

KEY = "test-admin-key-0123456789abcdef"
AUTH = {"X-Admin-Key": KEY}

transport = ASGITransport(app=app)


@pytest.fixture
def client():
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", KEY)


async def _seed(ac, n=2, category="benchmark"):
    """Create n quotes; order the first one."""
    spec = {"category": category, "item_type": "flyer", "quantity": 250,
            "paper_size": "A4", "paper_finish": "matte", "print_side": "single",
            "color_mode": "black_white", "urgency": "standard"}
    ids = []
    for i in range(n):
        r = await ac.post("/calculate-quote", json={"spec": spec, "raw_query": f"job number {i}"})
        ids.append(r.json()["id"])
    await ac.post("/orders", json={"quote_id": ids[0], "client_name": "Ekema Ltd",
                                   "client_contact": "677000000"})
    return ids


# ------------------------------------------------------------------ auth ---

ADMIN_ROUTES = ["/admin/session", "/admin/stats", "/admin/quotes", "/admin/orders", "/admin/export"]
STAFF_ROUTES = ["/orders"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADMIN_ROUTES + STAFF_ROUTES)
async def test_unconfigured_server_refuses_rather_than_falling_open(client, monkeypatch, path):
    """No key set must mean closed, never open."""
    monkeypatch.setattr(settings, "admin_api_key", "")
    async with client as ac:
        res = await ac.get(path)
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADMIN_ROUTES + STAFF_ROUTES)
async def test_development_mode_does_not_bypass_auth(client, monkeypatch, path):
    """The old guard returned early when ENVIRONMENT=development. It must not."""
    monkeypatch.setattr(settings, "admin_api_key", KEY)
    monkeypatch.setattr(settings, "environment", "development")
    async with client as ac:
        res = await ac.get(path)
    assert res.status_code == 401, f"{path} fell open in development mode"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADMIN_ROUTES + STAFF_ROUTES)
async def test_missing_and_wrong_keys_are_rejected(client, configured, path):
    async with client as ac:
        assert (await ac.get(path)).status_code == 401
        assert (await ac.get(path, headers={"X-Admin-Key": "wrong"})).status_code == 401


@pytest.mark.asyncio
async def test_short_key_is_refused_as_too_weak(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "short")
    async with client as ac:
        res = await ac.get("/admin/stats")
    assert res.status_code == 503
    assert "too weak" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bearer_token_is_accepted_too(client, configured):
    async with client as ac:
        res = await ac.get("/admin/session", headers={"Authorization": f"Bearer {KEY}"})
    assert res.status_code == 200
    assert res.json()["ok"] is True


@pytest.mark.asyncio
async def test_customer_endpoints_stay_public(client, configured):
    """Locking the back office must not lock customers out of quoting."""
    async with client as ac:
        assert (await ac.get("/health")).status_code == 200
        assert (await ac.get("/categories")).status_code == 200
        extract = await ac.post("/extract-specs", json={"query": "500 A4 flyers"})
        assert extract.status_code == 200
        quote = await ac.post("/calculate-quote", json={"spec": extract.json()["spec"]})
        assert quote.status_code == 200
        # Placing an order returns the receipt directly, so no admin call is needed.
        order = await ac.post("/orders", json={"quote_id": quote.json()["id"]})
        assert order.status_code == 200
        assert order.json()["total_xaf"] == quote.json()["total_xaf"]


# --------------------------------------------------------------- history ---

@pytest.mark.asyncio
async def test_quote_history_lists_newest_first_with_order_counts(client, configured):
    async with client as ac:
        await _seed(ac, n=3)
        res = await ac.get("/admin/quotes", headers=AUTH)

    body = res.json()
    assert body["total"] >= 3
    assert len(body["items"]) >= 3
    times = [i["created_at"] for i in body["items"]]
    assert times == sorted(times, reverse=True), "newest first"
    assert any(i["order_count"] >= 1 for i in body["items"]), "ordered quotes are marked"
    assert body["items"][0]["parameters"] is not None


@pytest.mark.asyncio
async def test_order_history_joins_the_originating_quote(client, configured):
    async with client as ac:
        await _seed(ac)
        res = await ac.get("/admin/orders", headers=AUTH)

    row = res.json()["items"][0]
    assert row["client_name"] == "Ekema Ltd"
    assert row["client_contact"] == "677000000"
    assert row["category"] == "benchmark"
    assert row["total_xaf"] > 0
    assert row["raw_query"]


@pytest.mark.asyncio
async def test_search_and_category_filters(client, configured):
    async with client as ac:
        await _seed(ac, n=2, category="benchmark")
        hit = await ac.get("/admin/quotes", params={"q": "job number"}, headers=AUTH)
        miss = await ac.get("/admin/quotes", params={"q": "zzzz-no-such-job"}, headers=AUTH)
        wrong_cat = await ac.get("/admin/quotes", params={"category": "merch", "q": "job number"},
                                 headers=AUTH)
    assert hit.json()["total"] >= 2
    assert miss.json()["total"] == 0
    assert wrong_cat.json()["total"] == 0


@pytest.mark.asyncio
async def test_date_filter_excludes_out_of_range(client, configured):
    async with client as ac:
        await _seed(ac, n=1)
        past = await ac.get("/admin/quotes",
                            params={"date_from": "2000-01-01", "date_to": "2000-01-02"},
                            headers=AUTH)
        today = await ac.get("/admin/quotes", params={"date_from": "2000-01-01"}, headers=AUTH)
    assert past.json()["total"] == 0
    assert today.json()["total"] >= 1


@pytest.mark.asyncio
async def test_pagination(client, configured):
    async with client as ac:
        await _seed(ac, n=4)
        first = await ac.get("/admin/quotes", params={"limit": 2, "offset": 0}, headers=AUTH)
        second = await ac.get("/admin/quotes", params={"limit": 2, "offset": 2}, headers=AUTH)

    a, b = first.json(), second.json()
    assert len(a["items"]) == 2 and len(b["items"]) == 2
    assert a["total"] == b["total"]
    assert {i["id"] for i in a["items"]}.isdisjoint({i["id"] for i in b["items"]})


@pytest.mark.asyncio
async def test_stats(client, configured):
    async with client as ac:
        await _seed(ac, n=3)
        body = (await ac.get("/admin/stats", headers=AUTH)).json()

    assert body["quotes_total"] >= 3
    assert body["orders_total"] >= 1
    assert 0 <= body["conversion_percent"] <= 100
    assert body["ordered_value_xaf"] > 0
    assert any(c["category"] == "benchmark" for c in body["by_category"])


# ---------------------------------------------------------------- export ---

@pytest.mark.asyncio
async def test_csv_export_downloads_as_a_file(client, configured):
    async with client as ac:
        await _seed(ac, n=2)
        res = await ac.get("/admin/export", params={"dataset": "quotes"}, headers=AUTH)

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    cd = res.headers["content-disposition"]
    assert cd.startswith("attachment;") and cd.endswith('.csv"')

    text = res.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) >= 2
    assert {"quote_id", "total_xaf", "raw_query", "parameters_json"} <= set(rows[0])
    # JSONB survives the CSV round-trip as parseable JSON.
    assert json.loads(rows[0]["parameters_json"])["category"] == "benchmark"


@pytest.mark.asyncio
async def test_csv_is_excel_safe_utf8(client, configured):
    """Without the BOM, Excel on Windows mangles accented client names."""
    async with client as ac:
        await _seed(ac, n=1)
        res = await ac.get("/admin/export", params={"dataset": "orders"}, headers=AUTH)
    assert res.content.startswith(b"\xef\xbb\xbf")


@pytest.mark.asyncio
async def test_json_export_keeps_nested_payloads(client, configured):
    async with client as ac:
        await _seed(ac, n=2)
        res = await ac.get("/admin/export",
                           params={"dataset": "quotes", "format": "json"}, headers=AUTH)

    body = json.loads(res.content)
    assert body["dataset"] == "quotes"
    assert body["row_count"] == len(body["rows"]) >= 2
    assert res.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_export_honours_the_same_filters_as_the_screen(client, configured):
    async with client as ac:
        await _seed(ac, n=2)
        res = await ac.get("/admin/export",
                           params={"dataset": "quotes", "q": "zzzz-no-such-job"}, headers=AUTH)
    rows = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows == []
    assert res.headers["X-Row-Count"] == "0"


@pytest.mark.asyncio
async def test_export_requires_the_key(client, configured):
    async with client as ac:
        res = await ac.get("/admin/export", params={"dataset": "orders"})
    assert res.status_code == 401
