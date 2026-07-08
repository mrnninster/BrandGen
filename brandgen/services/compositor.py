"""Programmatic typography + logo overlay (AI never draws the logo)."""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat

Corner = str  # top_left | top_right | bottom_left | bottom_right


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _corner_box(
    corner: Corner,
    *,
    width: int,
    height: int,
    box_w: int,
    box_h: int,
    margin_x: int,
    margin_y: int,
) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) for a logo plate anchored in a corner."""
    if corner == "top_left":
        x0, y0 = margin_x, margin_y
    elif corner == "top_right":
        x0, y0 = width - margin_x - box_w, margin_y
    elif corner == "bottom_left":
        x0, y0 = margin_x, height - margin_y - box_h
    else:  # bottom_right
        x0, y0 = width - margin_x - box_w, height - margin_y - box_h
    return x0, y0, x0 + box_w, y0 + box_h


def _region_busy_score(base: Image.Image, box: tuple[int, int, int, int]) -> float:
    """
    Higher = more visual activity — worse place for a logo.

    Combines edge energy, local contrast, and how much the patch differs
    from typical border/background tones (so solid graphic blocks score high).
    """
    x0, y0, x1, y1 = box
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(base.width, x1)
    y1 = min(base.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 1e9

    rgb = base.convert("RGB")
    crop = rgb.crop((x0, y0, x1, y1))
    gray = crop.convert("L")

    # Edge / detail energy
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mean = float(ImageStat.Stat(edges).mean[0])
    luma_std = float(ImageStat.Stat(gray).stddev[0])

    # Background reference: thin strips along the image border
    w, h = rgb.size
    strip = max(4, min(w, h) // 40)
    border_samples = [
        rgb.crop((0, 0, w, strip)),
        rgb.crop((0, h - strip, w, h)),
        rgb.crop((0, 0, strip, h)),
        rgb.crop((w - strip, 0, w, h)),
    ]
    border = Image.new("RGB", (strip * 4, strip))
    # Simpler: average border luminance/color via ImageStat on each strip
    br = bg = bb = 0.0
    for sample in border_samples:
        st = ImageStat.Stat(sample)
        br += st.mean[0]
        bg += st.mean[1]
        bb += st.mean[2]
    br /= 4
    bg /= 4
    bb /= 4

    crop_stat = ImageStat.Stat(crop)
    cr, cg, cb = crop_stat.mean
    # Distance from border/background color — subject-colored corners score higher
    color_delta = ((cr - br) ** 2 + (cg - bg) ** 2 + (cb - bb) ** 2) ** 0.5

    # Saturated / vivid patches are more likely “content”
    mx = max(cr, cg, cb)
    mn = min(cr, cg, cb)
    saturation = (mx - mn) / 255.0 if mx > 1 else 0.0

    return (
        edge_mean * 3.0
        + luma_std * 1.4
        + color_delta * 0.35
        + saturation * 40.0
    )


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def choose_logo_corner(
    base_image: Image.Image,
    *,
    logo_w: int,
    logo_h: int,
    pad: int = 10,
    margin_ratio: float = 0.05,
    avoid_boxes: list[tuple[int, int, int, int]] | None = None,
    preferred: Corner | None = None,
) -> tuple[Corner, tuple[int, int, int, int]]:
    """
    Pick the least-busy corner for the logo plate among the four corners.
    Soft-penalizes corners that overlap avoid_boxes (e.g. headline area).
    """
    width, height = base_image.size
    margin_x = max(8, int(width * margin_ratio))
    margin_y = max(8, int(height * margin_ratio))
    box_w = logo_w + pad * 2
    box_h = logo_h + pad * 2
    avoid_boxes = avoid_boxes or []

    candidates: list[Corner] = ["top_left", "top_right", "bottom_left", "bottom_right"]
    scored: list[tuple[float, Corner, tuple[int, int, int, int]]] = []

    for corner in candidates:
        box = _corner_box(
            corner,
            width=width,
            height=height,
            box_w=box_w,
            box_h=box_h,
            margin_x=margin_x,
            margin_y=margin_y,
        )
        score = _region_busy_score(base_image, box)
        for avoid in avoid_boxes:
            if _rects_overlap(box, avoid):
                # Prefer any free corner over covering headline / OCR text zone
                score += 250.0
        if preferred and corner == preferred:
            score -= 4.0
        scored.append((score, corner, box))

    scored.sort(key=lambda item: item[0])
    _, best_corner, best_box = scored[0]
    return best_corner, best_box


def _paste_logo(
    overlay: Image.Image,
    base_image: Image.Image,
    *,
    logo_path: str | Path | None,
    avoid_boxes: list[tuple[int, int, int, int]] | None = None,
) -> Corner | None:
    """Place logo in the least obstructive corner. Returns chosen corner or None."""
    if not logo_path or not Path(logo_path).exists():
        return None
    try:
        logo = Image.open(logo_path).convert("RGBA")
        width, height = base_image.size
        max_w = int(width * 0.18)
        max_h = int(height * 0.10)
        logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

        pad = max(8, int(min(width, height) * 0.012))
        corner, plate_box = choose_logo_corner(
            base_image,
            logo_w=logo.width,
            logo_h=logo.height,
            pad=pad,
            avoid_boxes=avoid_boxes,
            preferred="bottom_right",
        )
        px0, py0, _, _ = plate_box

        # Adaptive plate: light plate on dark region, dark plate on light region
        sample = base_image.crop(plate_box).convert("L")
        sample_mean = ImageStat.Stat(sample).mean[0]
        if sample_mean < 140:
            plate_color = (255, 255, 255, 200)
        else:
            plate_color = (12, 16, 28, 190)

        plate = Image.new(
            "RGBA",
            (logo.width + pad * 2, logo.height + pad * 2),
            plate_color,
        )
        # Soft rounded look via slight alpha fade on corners is overkill; keep simple plate
        overlay.paste(plate, (px0, py0), plate)
        overlay.paste(logo, (px0 + pad, py0 + pad), logo)
        return corner
    except Exception:  # noqa: BLE001
        return None


def composite_brand_overlay(
    base_image: Image.Image,
    *,
    headline: str,
    accent_hex: str,
    text_hex: str = "#ffffff",
    logo_path: str | Path | None = None,
    include_headline: bool = True,
    include_logo: bool = True,
) -> Image.Image:
    """
    Overlay brand accent bar + optional headline + real logo onto the AI image.

    Logo is placed in whichever of the 4 corners is least visually busy,
    and steered away from the headline region when typography is overlaid.
    """
    img = base_image.convert("RGBA")
    width, height = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    avoid_boxes: list[tuple[int, int, int, int]] = []

    accent = _hex_to_rgb(accent_hex)
    bar_h = max(6, height // 80)
    draw.rectangle([(0, 0), (width, bar_h)], fill=(*accent, 255))

    if include_headline and headline:
        wash_h = int(height * 0.28)
        for y in range(0, wash_h):
            alpha = int(140 * (1 - y / wash_h))
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

        font_size = max(28, width // 18)
        font = _load_font(font_size)
        wrapped = textwrap.fill(headline, width=22)
        text_color = (*_hex_to_rgb(text_hex), 255)
        text_xy = (int(width * 0.06), int(height * 0.08))
        draw.multiline_text(
            (text_xy[0] + 2, text_xy[1] + 2),
            wrapped,
            font=font,
            fill=(0, 0, 0, 160),
            spacing=8,
        )
        draw.multiline_text(
            text_xy,
            wrapped,
            font=font,
            fill=text_color,
            spacing=8,
        )
        # Approximate headline bounding box so logo avoids covering it
        try:
            bbox = draw.multiline_textbbox(text_xy, wrapped, font=font, spacing=8)
            avoid_boxes.append(
                (
                    max(0, bbox[0] - 12),
                    max(0, bbox[1] - 12),
                    min(width, bbox[2] + 12),
                    min(height, bbox[3] + 12),
                )
            )
        except Exception:  # noqa: BLE001
            avoid_boxes.append((0, 0, int(width * 0.7), int(height * 0.32)))

    if include_logo:
        _paste_logo(
            overlay,
            img,
            logo_path=logo_path,
            avoid_boxes=avoid_boxes,
        )

    composed = Image.alpha_composite(img, overlay)
    return composed.convert("RGB")


def save_jpeg(image: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
