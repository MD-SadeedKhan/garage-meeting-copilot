"""
Garage Meeting Copilot — OCR API Endpoint
Receives screenshots from desktop agent and returns extracted text.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.database import get_db
from app.middleware.garage_auth import GarageAuthContext, require_garage_auth
from app.services.ocr.screen_ocr import screen_ocr_pipeline

router = APIRouter(prefix="/api/v1/copilot", tags=["OCR"])


class OCRRequest(BaseModel):
    session_id: str
    image_data: str  # base64-encoded PNG/JPEG


class OCRResponse(BaseModel):
    session_id: str
    extracted_text: str
    cleaned_text: str
    word_count: int
    confidence: float
    application_hint: str | None


@router.post("/ocr", response_model=OCRResponse)
async def process_screenshot(
    request: OCRRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
) -> OCRResponse:
    """
    Process a screenshot from the desktop agent via OCR.
    Returns cleaned text for AI context enrichment.
    """
    if not request.image_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_data is required",
        )

    result = await screen_ocr_pipeline.process_screenshot(
        image_data=request.image_data,
        session_id=request.session_id,
    )

    return OCRResponse(
        session_id=request.session_id,
        extracted_text=result.extracted_text,
        cleaned_text=result.cleaned_text,
        word_count=result.word_count,
        confidence=result.confidence,
        application_hint=result.application_hint,
    )
