"""
Book typesetting — the advanced/interior parameters.

Two things these guard. First that specifying typesetting costs something and
leaving it to house style does not, because that distinction is the whole
argument for charging it. Second that the layout maths the 3D page is drawn
from is actually derived from the spec, rather than being decorative.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

transport = ASGITransport(app=app)


@pytest.fixture
def client():
    return AsyncClient(transport=transport, base_url="http://test")


BOOK = {"category": "book", "item_type": "novel", "quantity": 800, "page_count": 128,
        "trim_size": "A5", "interior_gsm": 80, "cover_gsm": 250, "binding": "perfect",
        "cover_finish": "glossy", "color_mode": "black_white", "urgency": "standard"}


def with_interior(**kw):
    return {**BOOK, "interior": kw}


# --------------------------------------------------------------- pricing ---

@pytest.mark.asyncio
async def test_house_style_is_not_billed_as_typesetting(client):
    """Falling back to the shop's defaults is not layout work."""
    async with client as ac:
        res = await ac.post("/calculate-quote", json={"spec": BOOK})
    labels = [li["label"] for li in res.json()["breakdown"]]
    assert not any("Typesetting" in l for l in labels)


@pytest.mark.asyncio
async def test_specifying_typesetting_adds_a_one_off_charge(client):
    async with client as ac:
        plain = await ac.post("/calculate-quote", json={"spec": BOOK})
        typeset = await ac.post("/calculate-quote", json={"spec": with_interior(typeface="eb_garamond")})

    line = next(li for li in typeset.json()["breakdown"] if "Typesetting" in li["label"])
    assert "EB Garamond" in line["label"]
    assert "not per copy" in line["detail"], "layout is charged once, not per book"
    assert typeset.json()["subtotal_xaf"] > plain.json()["subtotal_xaf"]


@pytest.mark.asyncio
async def test_typesetting_does_not_scale_with_quantity(client):
    """800 copies of one layout is still one layout."""
    async with client as ac:
        small = await ac.post("/calculate-quote", json={
            "spec": {**with_interior(typeface="lora"), "quantity": 50}})
        large = await ac.post("/calculate-quote", json={
            "spec": {**with_interior(typeface="lora"), "quantity": 5000}})

    def typeset(r):
        return next(li["amount_xaf"] for li in r.json()["breakdown"] if "Typesetting" in li["label"])
    assert typeset(small) == typeset(large)


@pytest.mark.asyncio
async def test_premium_paper_tone_costs_more_but_the_default_does_not(client):
    async with client as ac:
        plain = await ac.post("/calculate-quote", json={"spec": BOOK})
        kraft = await ac.post("/calculate-quote", json={"spec": with_interior(paper_tone="kraft_brown")})

    def paper(r):
        return next(li["amount_xaf"] for li in r.json()["breakdown"] if "Interior paper" in li["label"])
    assert kraft.json() and paper(kraft) > paper(plain)
    # The house default must not quietly carry a premium.
    assert paper(plain) == pytest.approx(665600, abs=1)


@pytest.mark.asyncio
async def test_unreadable_choices_are_warned_about_not_silently_priced(client):
    async with client as ac:
        res = await ac.post("/calculate-quote", json={
            "spec": with_interior(typeface="caveat", font_size_pt=9, line_spacing=1.05)})
    warnings = " ".join(res.json()["warnings"])
    assert "sets small" in warnings and "13pt" in warnings
    assert "tight" in warnings


@pytest.mark.asyncio
async def test_legibility_advice_is_per_face_not_one_number(client):
    """Patrick Hand is fine at 12pt; Homemade Apple is not. The face decides."""
    async with client as ac:
        neat = await ac.post("/calculate-quote", json={
            "spec": with_interior(typeface="patrick_hand", font_size_pt=12)})
        script = await ac.post("/calculate-quote", json={
            "spec": with_interior(typeface="homemade_apple", font_size_pt=12)})

    assert not any("sets small" in w for w in neat.json()["warnings"])
    assert any("sets small" in w for w in script.json()["warnings"])


@pytest.mark.asyncio
async def test_display_faces_are_flagged_even_when_set_large(client):
    """Size does not rescue a face that is decorative by nature."""
    async with client as ac:
        res = await ac.post("/calculate-quote", json={
            "spec": with_interior(typeface="dancing_script", font_size_pt=18)})
    warnings = " ".join(res.json()["warnings"])
    assert "display face" in warnings
    assert "sets small" not in warnings, "18pt is not small; only the display note applies"


@pytest.mark.asyncio
async def test_a_body_safe_handwriting_face_draws_no_complaint(client):
    async with client as ac:
        res = await ac.post("/calculate-quote", json={
            "spec": with_interior(typeface="indie_flower", font_size_pt=13, line_spacing=1.5)})
    assert res.json()["warnings"] == []


@pytest.mark.asyncio
async def test_every_handwriting_face_previews(client):
    """Each hand must survive the whole pipeline, not just appear in a list."""
    async with client as ac:
        io = (await ac.get("/categories")).json()["book"]["interior_options"]
        hands = [f["value"] for f in io["typefaces"] if f["kind"] == "handwriting"]
        assert len(hands) >= 6, "a single handwriting option is not a choice"

        for face in hands:
            res = await ac.post("/preview-model", json={"spec": with_interior(typeface=face)})
            assert res.status_code == 200, face
            i = res.json()["interior"]
            assert i["typeface"] == face
            # The 3D page draws with this stack; without it the canvas would
            # silently fall back and the preview would misrepresent the type.
            assert i["typeface_css"].startswith("'"), face
            assert i["lines_per_page"] > 0, face


# --------------------------------------------------------------- preview ---

@pytest.mark.asyncio
async def test_preview_derives_the_page_layout_from_the_spec(client):
    async with client as ac:
        res = await ac.post("/preview-model", json={
            "spec": with_interior(typeface="lora", font_size_pt=11, line_spacing=1.45,
                                  margin_mm=18, text_align="justified", paper_tone="cream")})
    i = res.json()["interior"]
    assert i["typeface_css"].startswith("'Lora'")
    assert i["paper_tone_hex"].startswith("#")
    assert i["lines_per_page"] > 5
    assert 30 < i["chars_per_line"] < 100
    assert i["specified"] is True


@pytest.mark.asyncio
async def test_bigger_type_means_fewer_lines_on_the_page(client):
    async with client as ac:
        small = await ac.post("/preview-model", json={"spec": with_interior(font_size_pt=9)})
        large = await ac.post("/preview-model", json={"spec": with_interior(font_size_pt=16)})
    assert large.json()["interior"]["lines_per_page"] < small.json()["interior"]["lines_per_page"]


@pytest.mark.asyncio
async def test_wider_margins_mean_a_narrower_measure(client):
    async with client as ac:
        narrow = await ac.post("/preview-model", json={"spec": with_interior(margin_mm=10)})
        wide = await ac.post("/preview-model", json={"spec": with_interior(margin_mm=32)})
    assert wide.json()["interior"]["chars_per_line"] < narrow.json()["interior"]["chars_per_line"]


@pytest.mark.asyncio
async def test_a_book_with_no_interior_still_previews(client):
    """The advanced panel is optional; nothing may depend on it being opened."""
    async with client as ac:
        res = await ac.post("/preview-model", json={"spec": BOOK})
    i = res.json()["interior"]
    assert i["specified"] is False
    assert i["lines_per_page"] > 0


@pytest.mark.asyncio
async def test_unknown_typeface_falls_back_instead_of_breaking(client):
    async with client as ac:
        res = await ac.post("/preview-model", json={"spec": with_interior(typeface="comic_sans_9000")})
    assert res.status_code == 200
    assert res.json()["interior"]["typeface"] == "lora"


@pytest.mark.asyncio
async def test_out_of_range_values_are_rejected_at_the_schema(client):
    async with client as ac:
        res = await ac.post("/preview-model", json={"spec": with_interior(font_size_pt=200)})
    assert res.status_code == 422


# ------------------------------------------------------------ form options ---

@pytest.mark.asyncio
async def test_categories_exposes_the_typesetting_options(client):
    async with client as ac:
        io = (await ac.get("/categories")).json()["book"]["interior_options"]
    assert any(f["kind"] == "handwriting" for f in io["typefaces"]), "a handwriting face is offered"
    assert all("css" in f for f in io["typefaces"]), "the preview needs a font stack"
    assert any(t["rate_multiplier"] > 1 for t in io["paper_tones"])
    assert io["defaults"]["paper_tone"] in {t["value"] for t in io["paper_tones"]}
