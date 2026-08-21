from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.schemas import ExtractRequest, ExtractResponse
from app.services import nlp_extractor, preview

router = APIRouter(prefix="/extract-specs", tags=["NLP Extraction"])


@router.post("", response_model=ExtractResponse)
async def extract_specs(payload: ExtractRequest):
    """
    Turn a plain-text request into a category-scoped spec.

    Pass `category` to pin extraction to a production line (the UI does this
    once the user picks a category card); omit it to auto-detect.
    """
    exclusion = nlp_extractor.check_exclusions(payload.query)
    if exclusion.excluded:
        # Not an error — a deliberate guardrail. The UI shows the reason and
        # routes the client to a staff member instead of quoting.
        return ExtractResponse(
            raw_query=payload.query,
            category=None,
            category_confidence=0.0,
            spec=None,
            confidence_score=0.0,
            needs_confirmation=True,
            exclusion=exclusion,
        )

    category, cat_confidence, spec, confidence = nlp_extractor.extract(
        payload.query, payload.category
    )

    if spec is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Couldn't tell which production line this belongs to. "
                "Pick a category (Book, Merch or Benchmark) and try again."
            ),
        )

    return ExtractResponse(
        raw_query=payload.query,
        category=category,
        category_confidence=cat_confidence,
        spec=spec,
        confidence_score=confidence,
        needs_confirmation=confidence < settings.nlp_confidence_threshold,
        missing_fields=nlp_extractor.missing_fields(spec),
        exclusion=exclusion,
        preview=preview.build_preview(spec),
    )
