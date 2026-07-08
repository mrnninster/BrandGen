"""Normalize scraped / logo bytes into browser-friendly PNG/JPEG files."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class NormalizedImage:
    data: bytes
    ext: str  # .png | .jpg | .webp
    width: int = 0
    height: int = 0
    source_kind: str = "unknown"


def sniff_kind(data: bytes, hint_url: str = "") -> str:
    if not data:
        return "empty"
    head = data[:256].lstrip()
    lower_url = (hint_url or "").lower().split("?")[0]
    if head.startswith(b"<svg") or head.startswith(b"<?xml") and b"<svg" in data[:2000].lower():
        return "svg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "webp"
    if head.startswith(b"GIF8"):
        return "gif"
    if head[:4] == b"\x00\x00\x01\x00" or head[:4] == b"\x00\x00\x02\x00":
        return "ico"
    if lower_url.endswith(".svg"):
        return "svg"
    if lower_url.endswith(".ico"):
        return "ico"
    if lower_url.endswith(".png"):
        return "png"
    if lower_url.endswith((".jpg", ".jpeg")):
        return "jpeg"
    if lower_url.endswith(".webp"):
        return "webp"
    return "unknown"


def _svg_to_png(data: bytes, *, output_width: int = 512) -> bytes | None:
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=data, output_width=output_width)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SVG conversion failed: %s", exc)
        return None


def _pil_to_png(img: Image.Image) -> tuple[bytes, int, int]:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.width, img.height


def _open_best_frame(data: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        # Prefer largest frame for ICO
        try:
            if getattr(img, "n_frames", 1) > 1:
                best = None
                best_area = -1
                for i in range(img.n_frames):
                    img.seek(i)
                    area = img.size[0] * img.size[1]
                    if area > best_area:
                        best_area = area
                        best = img.copy()
                return best
        except Exception:  # noqa: BLE001
            pass
        return img.convert("RGBA") if img.mode != "RGBA" else img.copy()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pillow open failed: %s", exc)
        return None


def normalize_image_bytes(
    data: bytes,
    *,
    hint_url: str = "",
    prefer_png: bool = False,
    min_size: int = 24,
    svg_width: int = 512,
) -> NormalizedImage | None:
    """
    Convert SVG/ICO/etc into a displayable raster file.
    Returns None when the payload is empty or unusable.
    """
    if not data or len(data) < 32:
        return None

    kind = sniff_kind(data, hint_url)

    if kind == "svg":
        png = _svg_to_png(data, output_width=svg_width)
        if not png:
            return None
        img = _open_best_frame(png)
        if not img:
            return None
        out, w, h = _pil_to_png(img)
        if max(w, h) < min_size:
            return None
        return NormalizedImage(data=out, ext=".png", width=w, height=h, source_kind="svg")

    img = _open_best_frame(data)
    if img is None and kind in {"png", "jpeg", "webp", "gif", "ico", "unknown"}:
        return None
    if img is None:
        return None

    w, h = img.size
    if max(w, h) < min_size:
        return None

    # Always normalize ICO / weird formats to PNG for reliable browser display
    if kind in {"ico", "gif", "unknown"} or prefer_png or img.mode == "RGBA":
        out, w, h = _pil_to_png(img)
        return NormalizedImage(data=out, ext=".png", width=w, height=h, source_kind=kind)

    if kind == "jpeg" or (kind == "unknown" and prefer_png is False):
        rgb = img.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=90, optimize=True)
        return NormalizedImage(
            data=buf.getvalue(),
            ext=".jpg",
            width=rgb.width,
            height=rgb.height,
            source_kind=kind or "jpeg",
        )

    if kind == "webp":
        out, w, h = _pil_to_png(img)
        return NormalizedImage(data=out, ext=".png", width=w, height=h, source_kind="webp")

    out, w, h = _pil_to_png(img)
    return NormalizedImage(data=out, ext=".png", width=w, height=h, source_kind=kind)
