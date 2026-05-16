"""
Garage Meeting Copilot — Screen OCR Pipeline
OpenCV + Tesseract based screen context extraction.
Receives screenshots from desktop agent, extracts text for AI context.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)


class ScreenOCRResult:
    """Result from OCR processing of a screenshot."""

    __slots__ = (
        "extracted_text",
        "cleaned_text",
        "word_count",
        "confidence",
        "regions",
        "application_hint",
    )

    def __init__(
        self,
        extracted_text: str,
        cleaned_text: str,
        word_count: int,
        confidence: float,
        regions: list[dict[str, Any]],
        application_hint: str | None,
    ) -> None:
        self.extracted_text = extracted_text
        self.cleaned_text = cleaned_text
        self.word_count = word_count
        self.confidence = confidence
        self.regions = regions
        self.application_hint = application_hint

    def to_dict(self) -> dict[str, Any]:
        return {
            "extracted_text": self.extracted_text,
            "cleaned_text": self.cleaned_text,
            "word_count": self.word_count,
            "confidence": self.confidence,
            "application_hint": self.application_hint,
        }


class ScreenOCRPipeline:
    """
    Multi-stage screen OCR pipeline:
    1. Decode incoming base64 image from desktop agent
    2. Preprocess with OpenCV (denoise, threshold, enhance)
    3. OCR with Tesseract
    4. Clean and structure extracted text
    5. Return for AI context enrichment
    """

    # Tesseract config for screen text (mixed font sizes)
    TESSERACT_CONFIG = (
        "--oem 3 --psm 11 "
        "-c tessedit_char_whitelist="
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789 .,!?;:'\"-()[]{}/@#$%&*+=<>\\n"
    )

    # Regions of interest multipliers (skip bottom taskbar, top menubar)
    ROI_TOP_FRACTION = 0.05
    ROI_BOTTOM_FRACTION = 0.92

    def __init__(self) -> None:
        self._verify_tesseract()

    def _verify_tesseract(self) -> None:
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            logger.warning("tesseract_not_available", error=str(e))

    def decode_image(self, image_data: str | bytes) -> np.ndarray:
        """Decode base64 or raw bytes to OpenCV image array."""
        if isinstance(image_data, str):
            # Strip data URI prefix if present
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw = base64.b64decode(image_data)
        else:
            raw = image_data

        img_array = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Failed to decode image data")
        return img

    def preprocess(self, img: np.ndarray) -> np.ndarray:
        """
        Multi-stage preprocessing for optimal OCR accuracy:
        - Convert to grayscale
        - Apply CLAHE contrast enhancement
        - Denoise
        - Adaptive threshold for binarization
        - Morphological cleanup
        """
        # Crop to region of interest
        h, w = img.shape[:2]
        top = int(h * self.ROI_TOP_FRACTION)
        bottom = int(h * self.ROI_BOTTOM_FRACTION)
        img = img[top:bottom, 0:w]

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # Denoise
        denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

        # Scale up for better OCR (if image is small)
        height, width = denoised.shape
        if width < 1920:
            scale = 1920 / width
            denoised = cv2.resize(
                denoised,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )

        # Adaptive threshold
        binary = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )

        # Morphological cleanup
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return cleaned

    def extract_text(self, processed_img: np.ndarray) -> tuple[str, float]:
        """Run Tesseract OCR and return (text, avg_confidence)."""
        try:
            # Get detailed OCR data for confidence scoring
            data = pytesseract.image_to_data(
                processed_img,
                config=self.TESSERACT_CONFIG,
                output_type=pytesseract.Output.DICT,
            )

            words = []
            confidences = []

            for i, conf in enumerate(data["conf"]):
                if isinstance(conf, (int, float)) and conf > 30:
                    word = data["text"][i].strip()
                    if word:
                        words.append(word)
                        confidences.append(float(conf))

            text = " ".join(words)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            return text, avg_conf / 100.0

        except Exception as e:
            logger.warning("tesseract_ocr_failed", error=str(e))
            # Fallback: basic string extraction
            try:
                text = pytesseract.image_to_string(processed_img)
                return text, 0.5
            except Exception:
                return "", 0.0

    def clean_text(self, raw_text: str) -> str:
        """
        Clean and normalize OCR output:
        - Remove excessive whitespace
        - Remove garbage characters (very short isolated chars)
        - Normalize newlines
        - Remove duplicate lines
        """
        if not raw_text:
            return ""

        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", raw_text)

        # Split into lines and clean each
        lines = text.split("\n")
        cleaned_lines = []
        seen = set()

        for line in lines:
            line = line.strip()
            # Skip empty or very short lines (OCR noise)
            if len(line) < 3:
                continue
            # Skip lines that are mostly non-alphanumeric (garbage)
            alnum_ratio = sum(c.isalnum() or c.isspace() for c in line) / len(line)
            if alnum_ratio < 0.5:
                continue
            # Deduplicate
            line_key = line.lower().strip()
            if line_key not in seen:
                seen.add(line_key)
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def detect_application_hint(self, img: np.ndarray) -> str | None:
        """
        Heuristic detection of the active application from the screenshot.
        Looks for common application title bar patterns.
        """
        # Extract top 10% of image where title bars typically live
        h = img.shape[0]
        title_region = img[0 : int(h * 0.08), :]

        gray = cv2.cvtColor(title_region, cv2.COLOR_BGR2GRAY)
        try:
            title_text = pytesseract.image_to_string(gray, config="--psm 7").strip()
            if title_text:
                return title_text[:200]
        except Exception:
            pass
        return None

    async def process_screenshot(
        self,
        image_data: str | bytes,
        session_id: str,
    ) -> ScreenOCRResult:
        """
        Full pipeline: decode → preprocess → OCR → clean → return.
        """
        try:
            img = self.decode_image(image_data)
            app_hint = self.detect_application_hint(img)
            processed = self.preprocess(img)
            raw_text, confidence = self.extract_text(processed)
            cleaned = self.clean_text(raw_text)
            word_count = len(cleaned.split()) if cleaned else 0

            logger.debug(
                "screen_ocr_complete",
                session_id=session_id,
                word_count=word_count,
                confidence=round(confidence, 3),
            )

            return ScreenOCRResult(
                extracted_text=raw_text,
                cleaned_text=cleaned,
                word_count=word_count,
                confidence=confidence,
                regions=[],
                application_hint=app_hint,
            )

        except Exception as e:
            logger.error(
                "screen_ocr_pipeline_error",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return ScreenOCRResult(
                extracted_text="",
                cleaned_text="",
                word_count=0,
                confidence=0.0,
                regions=[],
                application_hint=None,
            )

    def truncate_for_context(self, text: str, max_tokens: int = 500) -> str:
        """
        Truncate screen context text to reasonable token budget.
        Roughly 4 chars per token.
        """
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        # Truncate at word boundary
        truncated = text[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.8:
            truncated = truncated[:last_space]
        return truncated + "..."


# Module-level singleton
screen_ocr_pipeline = ScreenOCRPipeline()
