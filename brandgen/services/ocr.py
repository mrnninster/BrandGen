"""OCR helpers — detect AI-rendered text and decide whether overlay is needed."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)

# Common OCR garbage / tiny watermark leftovers to ignore
NOISE_RE = re.compile(r"[^\w\s'\"&.\-:!?]", re.UNICODE)
WORD_RE = re.compile(r"[A-Za-z]{2,}")


@dataclass
class TextQuality:
    has_text: bool
    text_is_usable: bool
    raw_text: str
    reason: str

    @property
    def needs_text_overlay(self) -> bool:
        """True when we should regenerate (if needed) and burn in headline text."""
        return not self.text_is_usable


def extract_text(image: Image.Image) -> str:
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not installed — skipping OCR")
        return ""

    try:
        rgb = image.convert("RGB")
        # Slight upscale helps small typography on 1024 canvases
        w, h = rgb.size
        if max(w, h) < 1400:
            rgb = rgb.resize((int(w * 1.4), int(h * 1.4)), Image.Resampling.LANCZOS)
        text = pytesseract.image_to_string(rgb) or ""
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed: %s", exc)
        return ""


def _normalize(text: str) -> str:
    text = text.lower()
    text = NOISE_RE.sub(" ", text)
    return " ".join(text.split())


def _token_set(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text)}


def _looks_garbled(text: str) -> bool:
    """Heuristic: lots of short junk tokens or weird punctuation density."""
    words = WORD_RE.findall(text)
    if not words:
        return True
    short = sum(1 for w in words if len(w) <= 2)
    if len(words) >= 4 and short / len(words) > 0.6:
        return True
    # High non-alnum ratio in original
    clean = re.sub(r"\s+", "", text)
    if not clean:
        return True
    weird = sum(1 for c in clean if not c.isalnum() and c not in "'\"&.-!?:")
    if weird / len(clean) > 0.25:
        return True
    return False


def evaluate_rendered_text(image: Image.Image, *, headline: str, brand_name: str = "") -> TextQuality:
    """
    Decide if the AI image already has usable headline-like text.

    - No / tiny OCR text → overlay needed
    - OCR text exists and overlaps headline (or is readable & long enough) → keep AI text
    - OCR text is garbled / unrelated nonsense → regenerate without text + overlay
    """
    raw = extract_text(image)
    normalized = _normalize(raw)
    words = WORD_RE.findall(raw)

    if len(normalized) < 6 or len(words) < 2:
        return TextQuality(
            has_text=False,
            text_is_usable=False,
            raw_text=raw,
            reason="little_or_no_text",
        )

    if _looks_garbled(raw):
        return TextQuality(
            has_text=True,
            text_is_usable=False,
            raw_text=raw,
            reason="garbled_text",
        )

    headline_tokens = _token_set(headline)
    ocr_tokens = _token_set(raw)
    # Drop ultra-common filler
    stop = {"the", "and", "for", "with", "your", "our", "a", "an", "to", "of", "in", "on"}
    headline_tokens -= stop
    brand_tokens = _token_set(brand_name) - stop

    overlap = headline_tokens & ocr_tokens if headline_tokens else set()
    brand_overlap = brand_tokens & ocr_tokens if brand_tokens else set()

    # Strong match to intended headline → usable
    if headline_tokens and len(overlap) >= max(1, len(headline_tokens) // 2):
        return TextQuality(
            has_text=True,
            text_is_usable=True,
            raw_text=raw,
            reason="headline_match",
        )

    # Readable multi-word phrase that isn't just the brand logo letters
    if len(words) >= 3 and len(normalized) >= 12:
        # If OCR is only brand name noise, treat as not usable headline
        if brand_tokens and ocr_tokens <= brand_tokens | stop:
            return TextQuality(
                has_text=True,
                text_is_usable=False,
                raw_text=raw,
                reason="brand_only",
            )
        return TextQuality(
            has_text=True,
            text_is_usable=True,
            raw_text=raw,
            reason="readable_copy",
        )

    if brand_overlap and not overlap and len(words) <= 3:
        return TextQuality(
            has_text=True,
            text_is_usable=False,
            raw_text=raw,
            reason="brand_only",
        )

    return TextQuality(
        has_text=True,
        text_is_usable=False,
        raw_text=raw,
        reason="unrelated_or_weak",
    )
