import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

transport = ASGITransport(app=app)


@pytest.fixture
def client():
    return AsyncClient(transport=transport, base_url="http://test")


# ------------------------------------------------------------------ system ---

@pytest.mark.asyncio
async def test_health(client):
    async with client as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_categories_metadata_drives_the_ui(client):
    async with client as ac:
        res = await ac.get("/categories")
    assert res.status_code == 200
    data = res.json()
    assert set(data) >= {"book", "merch", "benchmark"}
    assert "perfect" in data["book"]["options"]["binding"]
    assert "mug" in data["merch"]["options"]["item_type"]


# -------------------------------------------------------- category routing ---

@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("500 A4 glossy flyers, double sided full colour", "benchmark"),
    ("200 copies of a 96 page A5 textbook, perfect bound", "book"),
    ("50 white t-shirts, screen printed front, 2 colours", "merch"),
    ("30 sublimated mugs with a wrap print", "merch"),
])
async def test_category_is_auto_detected(client, query, expected):
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": query})
    assert res.status_code == 200
    assert res.json()["category"] == expected


@pytest.mark.asyncio
async def test_explicit_category_overrides_detection(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={
            "query": "300 of them, A5, glossy",
            "category": "benchmark",
        })
    data = res.json()
    assert data["category"] == "benchmark"
    assert data["category_confidence"] == 1.0
    assert data["spec"]["paper_size"] == "A5"


@pytest.mark.asyncio
async def test_undetectable_category_is_a_422_not_a_guess(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": "I need some stuff printed"})
    assert res.status_code == 422


# ------------------------------------------------------------- guardrails ---

@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "500 branded pens for a conference",
    "200 ID cards for staff",
])
async def test_excluded_products_are_refused_with_a_reason(client, query):
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": query})
    assert res.status_code == 200
    data = res.json()
    assert data["exclusion"]["excluded"] is True
    assert data["exclusion"]["matched_terms"]
    assert data["exclusion"]["reason"]
    assert data["spec"] is None


# ------------------------------------------------- extraction: benchmark ---

@pytest.mark.asyncio
async def test_benchmark_extraction(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={
            "query": "I need 500 copies of A4 glossy flyers, double-sided full color, urgent",
        })
    data = res.json()
    spec = data["spec"]
    assert spec["category"] == "benchmark"
    assert spec["quantity"] == 500
    assert spec["paper_size"] == "A4"
    assert spec["paper_finish"] == "glossy"
    assert spec["print_side"] == "double"
    assert spec["color_mode"] == "full_color"
    assert spec["urgency"] == "high"
    assert data["confidence_score"] == 1.0
    assert data["missing_fields"] == []


@pytest.mark.asyncio
async def test_unstated_fields_stay_null(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": "some posters"})
    data = res.json()
    spec = data["spec"]
    assert spec["quantity"] is None
    assert spec["paper_size"] is None
    assert spec["color_mode"] is None
    assert data["needs_confirmation"] is True
    assert "quantity" in data["missing_fields"]


# ------------------------------------------------------ extraction: book ---

@pytest.mark.asyncio
async def test_book_extraction_and_spine_geometry(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={
            "query": "1000 copies of a 200 page A5 novel, 80gsm interior, 250gsm cover, perfect bound, black and white",
        })
    data = res.json()
    spec = data["spec"]
    assert spec["category"] == "book"
    assert spec["quantity"] == 1000
    assert spec["page_count"] == 200
    assert spec["trim_size"] == "A5"
    assert spec["interior_gsm"] == 80
    assert spec["cover_gsm"] == 250
    assert spec["binding"] == "perfect"
    assert spec["color_mode"] == "black_white"

    preview = data["preview"]
    assert preview["kind"] == "book"
    # 100 leaves x 80gsm x 0.00125 = 10.0mm, + 2 x 250gsm cover boards = 10.625mm.
    assert preview["dimensions_mm"]["spine"] == pytest.approx(10.625, abs=0.01)
    assert preview["dimensions_mm"]["width"] == 148


@pytest.mark.asyncio
async def test_booklet_stays_benchmark_not_book(client):
    """'booklet' is flat-sheet work at Presprint — the router must not claim it."""
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": "300 A5 booklets, stapling"})
    assert res.json()["category"] == "benchmark"


# ----------------------------------------------------- extraction: merch ---

@pytest.mark.asyncio
@pytest.mark.parametrize("phrase,expected", [
    ("size L", "L"), ("size xl", "XL"), ("sizes M", "M"), ("large", "L"),
])
async def test_bare_letter_sizes_need_the_word_size(client, phrase, expected):
    async with client as ac:
        res = await ac.post("/extract-specs", json={"query": f"40 t-shirts {phrase}, screen print front"})
    assert res.json()["spec"]["garment_size"] == expected


@pytest.mark.asyncio
async def test_merch_extraction(client):
    async with client as ac:
        res = await ac.post("/extract-specs", json={
            "query": "100 navy t-shirts size XL, screen print front and back, 3 colours",
        })
    data = res.json()
    spec = data["spec"]
    assert spec["category"] == "merch"
    assert spec["item_type"] == "shirt"
    assert spec["quantity"] == 100
    assert spec["garment_size"] == "XL"
    assert spec["print_method"] == "screen"
    assert spec["color_count"] == 3
    assert set(spec["placements"]) == {"front", "back"}
    assert data["preview"]["kind"] == "tshirt"


# --------------------------------------------------------------- pricing ---

@pytest.mark.asyncio
async def test_benchmark_quote_math(client):
    """500 A4 matte, single-sided b/w: paper 60x500 + ink 10x500 = 35,000."""
    spec = {
        "category": "benchmark", "item_type": "flyer", "quantity": 500,
        "paper_size": "A4", "paper_finish": "matte", "print_side": "single",
        "color_mode": "black_white", "finishing": [], "urgency": "standard",
    }
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": spec})
    assert res.status_code == 200
    data = res.json()
    assert data["subtotal_xaf"] == 35000
    assert data["discount_xaf"] == 3500          # 10% tier at 500
    assert data["rush_fee_xaf"] == 0
    assert data["tax_xaf"] == pytest.approx(31500 * 0.1925, abs=0.01)
    assert data["total_xaf"] > data["subtotal_xaf"] - data["discount_xaf"]


@pytest.mark.asyncio
async def test_rush_fee_applies_only_when_urgent(client):
    base = {
        "category": "benchmark", "quantity": 100, "paper_size": "A4",
        "paper_finish": "matte", "print_side": "single", "color_mode": "black_white",
    }
    async with client as ac:
        standard = await ac.post("/calculate-quote", json={"spec": {**base, "urgency": "standard"}})
        rushed = await ac.post("/calculate-quote", json={"spec": {**base, "urgency": "high"}})
    assert standard.json()["rush_fee_xaf"] == 0
    assert rushed.json()["rush_fee_xaf"] > 0
    assert rushed.json()["total_xaf"] > standard.json()["total_xaf"]


@pytest.mark.asyncio
async def test_book_quote_is_itemised_by_component(client):
    spec = {
        "category": "book", "item_type": "novel", "quantity": 500, "page_count": 120,
        "trim_size": "A5", "interior_gsm": 80, "cover_gsm": 250, "binding": "perfect",
        "cover_finish": "glossy", "color_mode": "black_white", "urgency": "standard",
    }
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": spec})
    data = res.json()
    labels = " ".join(li["label"] for li in data["breakdown"])
    assert "Interior paper" in labels
    assert "Cover" in labels
    assert "Binding" in labels
    assert data["category"] == "book"
    assert data["preview"]["kind"] == "book"
    # Every line explains its own derivation, for UAT defence.
    assert all(li["detail"] for li in data["breakdown"])


@pytest.mark.asyncio
async def test_binding_page_limit_warns_instead_of_silently_pricing(client):
    spec = {
        "category": "book", "quantity": 100, "page_count": 300,
        "trim_size": "A5", "binding": "saddle_stitch", "color_mode": "black_white",
        "urgency": "standard",
    }
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": spec})
    warnings = " ".join(res.json()["warnings"])
    assert "saddle stitch" in warnings and "64" in warnings


@pytest.mark.asyncio
async def test_odd_page_count_rounds_to_a_signature(client):
    spec = {"category": "book", "quantity": 10, "page_count": 61, "urgency": "standard"}
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": spec})
    assert any("signature" in w for w in res.json()["warnings"])


@pytest.mark.asyncio
async def test_merch_screen_setup_scales_with_colours_and_placements(client):
    def spec(colors, placements):
        return {
            "category": "merch", "item_type": "shirt", "quantity": 50,
            "print_method": "screen", "color_count": colors,
            "placements": placements, "urgency": "standard",
        }

    async with client as ac:
        one = await ac.post("/calculate-quote", json={"spec": spec(1, ["front"])})
        many = await ac.post("/calculate-quote", json={"spec": spec(3, ["front", "back"])})
    assert many.json()["subtotal_xaf"] > one.json()["subtotal_xaf"]


@pytest.mark.asyncio
async def test_invalid_placement_is_dropped_with_a_warning(client):
    spec = {
        "category": "merch", "item_type": "mug", "quantity": 20,
        "print_method": "sublimation", "color_count": 4,
        "placements": ["sleeve"], "urgency": "standard",
    }
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": spec})
    assert any("sleeve" in w for w in res.json()["warnings"])


# --------------------------------------------------------------- preview ---

@pytest.mark.asyncio
async def test_preview_endpoint_tracks_page_count(client):
    def spec(pages):
        return {"category": "book", "page_count": pages, "interior_gsm": 80, "trim_size": "A5"}

    async with client as ac:
        thin = await ac.post("/preview-model", json={"spec": spec(64)})
        thick = await ac.post("/preview-model", json={"spec": spec(512)})
    assert thick.json()["dimensions_mm"]["spine"] > thin.json()["dimensions_mm"]["spine"]


# ---------------------------------------------------------------- orders ---

@pytest.mark.asyncio
async def test_order_flow_produces_a_receipt(client):
    spec = {
        "category": "benchmark", "item_type": "flyer", "quantity": 200,
        "paper_size": "A5", "paper_finish": "glossy", "print_side": "double",
        "color_mode": "full_color", "urgency": "standard",
    }
    async with client as ac:
        quote = (await ac.post("/calculate-quote", json={
            "spec": spec, "raw_query": "200 A5 glossy flyers double sided full colour",
        })).json()

        receipt = await ac.post("/orders", json={
            "quote_id": quote["id"],
            "client_name": "Ekema Print Supplies",
            "client_contact": "677000000",
        })
        assert receipt.status_code == 200
        r = receipt.json()
        assert r["total_xaf"] == quote["total_xaf"]
        assert r["category"] == "benchmark"
        assert r["parameters"]["paper_size"] == "A5"
        assert r["status"] == "pending"

        fetched = await ac.get(f"/orders/{r['order_id']}/receipt")
        assert fetched.json()["order_id"] == r["order_id"]


@pytest.mark.asyncio
async def test_order_against_unknown_quote_is_404(client):
    async with client as ac:
        res = await ac.post("/orders", json={"quote_id": "does-not-exist"})
    assert res.status_code == 404
