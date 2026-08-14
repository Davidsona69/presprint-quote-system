from fastapi import APIRouter

from app.core.config import settings
from app.schemas.schemas import ExtractRequest, ExtractResponse
from app.services import nlp_extractor

router = APIRouter(prefix="/extract-specs", tags=["NLP Extraction"])


@router.post("", response_model=ExtractResponse)
async def extract_specs(payload: ExtractRequest):
    entities, confidence = nlp_extractor.extract(payload.query)
    return ExtractResponse(
        raw_query=payload.query,
        extracted_entities=entities,
        confidence_score=confidence,
        needs_confirmation=confidence < settings.nlp_confidence_threshold,
    )
