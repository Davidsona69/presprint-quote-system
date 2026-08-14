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
