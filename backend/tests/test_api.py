"""
Run with: pytest tests/ -v
(requires the app + a test DB reachable — simplest is running against the
docker-compose db, or swapping DATABASE_URL to a local sqlite file for tests)
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_extract_specs_basic():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/extract-specs", json={
            "query": "I need 500 copies of A4 glossy flyers with double-sided color print by Friday"
        })
    assert res.status_code == 200
    data = res.json()
    ents = data["extracted_entities"]
    assert ents["quantity"] == 500
    assert ents["paper_size"] == "A4"
    assert ents["paper_finish"] == "glossy"
    assert ents["print_side"] == "double"
    assert ents["color_mode"] == "full_color"
    assert ents["urgency"] == "high"
    assert data["confidence_score"] > 0.5


@pytest.mark.asyncio
async def test_calculate_quote_basic():
    transport = ASGITransport(app=app)
    entities = {
        "item_type": "flyer", "quantity": 500, "paper_size": "A4",
        "paper_finish": "glossy", "print_side": "double", "color_mode": "full_color",
        "finishing": [], "urgency": "high",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/calculate-quote", json={"entities": entities})
    assert res.status_code == 200
    data = res.json()
    assert data["total_xaf"] > 0
    assert data["rush_fee_xaf"] > 0  # urgency=high should trigger rush fee


@pytest.mark.asyncio
async def test_place_order_and_receipt():
    transport = ASGITransport(app=app)
    entities = {
        "item_type": "flyer", "quantity": 200, "paper_size": "A4",
        "paper_finish": "matte", "print_side": "single", "color_mode": "full_color",
        "finishing": [], "urgency": "standard",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        quote_res = await ac.post("/calculate-quote", json={
            "entities": entities, "raw_query": "200 A4 flyers"
        })
        quote_id = quote_res.json()["id"]

        order_res = await ac.post("/orders", json={
            "quote_id": quote_id,
            "client_name": "Test Client Ltd",
            "client_contact": "670000000",
        })
        assert order_res.status_code == 200
        receipt = order_res.json()
        assert receipt["client_name"] == "Test Client Ltd"
        assert receipt["status"] == "pending"
        assert receipt["total_xaf"] == quote_res.json()["total_xaf"]
        assert len(receipt["breakdown"]) > 0

        order_id = receipt["order_id"]
        fetched = await ac.get(f"/orders/{order_id}/receipt")
        assert fetched.status_code == 200
        assert fetched.json()["order_id"] == order_id
