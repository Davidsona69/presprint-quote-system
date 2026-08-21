from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.schemas import PreviewConfig, Spec
from app.services import preview as preview_service

router = APIRouter(prefix="/preview-model", tags=["3D Preview"])


class PreviewRequest(BaseModel):
    spec: Spec


@router.post("", response_model=PreviewConfig)
async def preview_model(payload: PreviewRequest):
    """
    Recompute the parametric 3D viewport for a spec.

    Stateless and cheap on purpose — the frontend calls this on every field
    edit in the review step so the model on screen tracks the form live,
    without having to commit a quote to the database first.
    """
    return preview_service.build_preview(payload.spec)
