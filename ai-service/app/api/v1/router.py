"""
Garage Meeting Copilot — API Router
Aggregates all v1 endpoint routers.
"""
from fastapi import APIRouter

from app.api.v1.endpoints.exports import router as exports_router
from app.api.v1.endpoints.ocr import router as ocr_router

api_router = APIRouter()

api_router.include_router(ocr_router)
api_router.include_router(exports_router)
