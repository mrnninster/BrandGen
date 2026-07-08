"""OpenAI helpers — design system synthesis, vision labeling, image generation."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any

from django.conf import settings
from openai import OpenAI
from PIL import Image

logger = logging.getLogger(__name__)


def get_client(api_key: str | None = None) -> OpenAI:
    key = (api_key or settings.OPENAI_API_KEY or "").strip()
    if not key or key.startswith("sk-your"):
        raise RuntimeError(
            "No OpenAI API key available. Add your key in the app header, "
            "or configure OPENAI_API_KEY on the server."
        )
    return OpenAI(api_key=key)


def synthesize_design_system(
    *,
    brand_name: str,
    website_url: str,
    colors: list[str],
    fonts: list[str],
    site_summary: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Ask the LLM to invent a unique per-site design system from brand signals."""
    client = get_client(api_key)
    prompt = f"""
You are a senior brand designer. Build a UNIQUE visual design system for this website.
Never use a generic "startup purple gradient" look. Match this brand specifically.

Brand name: {brand_name}
URL: {website_url}
Extracted colors (ranked by CSS usage): {colors}
Detected fonts: {fonts}
Site copy excerpt:
{site_summary[:3500]}

Return STRICT JSON with this shape:
{{
  "mood": "short mood phrase",
  "color_roles": {{
    "background": "#hex",
    "surface": "#hex",
    "primary": "#hex",
    "accent": "#hex",
    "text": "#hex",
    "muted": "#hex"
  }},
  "typography": {{
    "display": "font name",
    "body": "font name",
    "headline_style": "e.g. bold condensed / airy geometric"
  }},
  "imagery_style": "how product/graphics should look (3d, flat, photo, isometric…)",
  "decoration_motifs": ["motif1", "motif2"],
  "layout_preferences": ["preference1", "preference2"],
  "negative_space_rules": "rules for empty space",
  "do_not": ["things to avoid"],
  "sample_hooks": ["3 punchy social headlines grounded in the brand"]
}}
Prefer the extracted hex colors when assigning roles. Invent missing roles by deriving harmonious tones.
""".strip()

    response = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": "You output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


def label_image_with_vision(image_url: str, alt_text: str = "", *, api_key: str | None = None) -> str:
    """Classify a site image as logo|product|photo|icon|other."""
    client = get_client(api_key)
    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_TEXT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Classify this website image. Reply with ONE word only: "
                                "logo, product, photo, icon, or other. "
                                f"Alt text hint: {alt_text or 'n/a'}"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=10,
            temperature=0,
        )
        label = (response.choices[0].message.content or "other").strip().lower()
        label = re.sub(r"[^a-z]", "", label)
        if label not in {"logo", "product", "photo", "icon", "other"}:
            return "other"
        return label
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision labeling failed for %s: %s", image_url, exc)
        return "other"


def build_image_prompt(
    *,
    brand_name: str,
    design_system: dict[str, Any],
    headline: str,
    body: str,
    slide_index: int,
    slide_count: int,
    platform: str,
    post_type: str,
    refine_instruction: str = "",
    force_no_text: bool = False,
) -> str:
    tokens = {
        "brand": brand_name,
        "palette": design_system.get("color_roles", {}),
        "typography": design_system.get("typography", {}),
        "imagery_style": design_system.get("imagery_style", ""),
        "motifs": design_system.get("decoration_motifs", []),
        "layout": design_system.get("layout_preferences", []),
        "negative_space": design_system.get("negative_space_rules", ""),
        "do_not": design_system.get("do_not", []),
        "platform": platform,
        "post_type": post_type,
        "slide": f"{slide_index + 1}/{slide_count}",
        "headline": headline,
        "supporting_copy": body,
    }
    refine_block = (
        f"\nRefinement instruction (preserve everything else): {refine_instruction}"
        if refine_instruction
        else ""
    )
    if force_no_text:
        text_rules = """
Rules:
- Use ONLY the hex colors in color_roles for backgrounds, accents, and shapes.
- CRITICAL: Absolutely NO letters, numbers, words, captions, UI chrome, signs, or typography of any kind in the image.
- Leave clear empty negative space in the upper third for a headline that will be composited programmatically.
- Do NOT render any logo or brand wordmark — the real logo file will be overlaid later.
- Match imagery_style and decoration motifs so every slide feels like one design system.
- Slide consistency: this is slide {slide} of {total}; keep the same palette, lighting, and motif language.
""".format(slide=slide_index + 1, total=slide_count)
    else:
        text_rules = f"""
Rules:
- Use ONLY the hex colors in color_roles for backgrounds, accents, and shapes.
- Prefer crisp visual design with optional short headline lettering that clearly reads: "{headline}".
- If you include text, it must be sharp, correctly spelled, and match the headline closely — no garbled / fake lorem letters.
- Leave clean space if you omit text; typography may be composited later.
- Do NOT render any logo, wordmark, watermark, or brand emblem — logo will be composited programmatically.
- Match imagery_style and decoration motifs so every slide feels like one design system.
- Slide consistency: this is slide {slide_index + 1} of {slide_count}; keep the same palette, lighting, and motif language.
"""
    return f"""
Create a publication-ready {platform} {post_type} graphic for "{brand_name}".
Square social format, premium design quality (3D objects, crisp geometry, intentional lighting when suitable).

DESIGN TOKENS (JSON — obey exactly):
{json.dumps(tokens, indent=2)}
{text_rules}
{refine_block}
""".strip()


def generate_image_bytes(prompt: str, size: str = "1024x1024", *, api_key: str | None = None) -> bytes:
    """Generate an image with OpenAI (gpt-image-1 preferred, dall-e-3 fallback)."""
    client = get_client(api_key)
    model = settings.OPENAI_IMAGE_MODEL
    errors: list[str] = []

    for candidate in (model, "gpt-image-1", "dall-e-3"):
        try:
            if candidate == "dall-e-3":
                result = client.images.generate(
                    model="dall-e-3",
                    prompt=prompt[:3900],
                    size="1024x1024",
                    quality="standard",
                    n=1,
                    response_format="b64_json",
                )
            else:
                # gpt-image-1 returns b64 by default
                result = client.images.generate(
                    model=candidate,
                    prompt=prompt,
                    size=size,
                    n=1,
                )
            item = result.data[0]
            if getattr(item, "b64_json", None):
                return base64.b64decode(item.b64_json)
            if getattr(item, "url", None):
                import requests

                resp = requests.get(item.url, timeout=60)
                resp.raise_for_status()
                return resp.content
            raise RuntimeError("Image response contained neither b64_json nor url")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {exc}")
            logger.warning("Image generation failed with %s: %s", candidate, exc)
            continue

    raise RuntimeError("All image models failed: " + " | ".join(errors))


def generate_captions_and_slides(
    *,
    brand_name: str,
    design_system: dict[str, Any],
    post_type: str,
    slide_count: int,
    site_summary: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Produce caption + per-slide headlines/body grounded in the brand."""
    client = get_client(api_key)
    hooks = design_system.get("sample_hooks", [])
    prompt = f"""
Write social content for {brand_name}.
Post type: {post_type}
Slide count: {slide_count}
Mood: {design_system.get('mood', '')}
Hooks: {hooks}
Site context:
{site_summary[:2500]}

Return JSON:
{{
  "caption": "platform-ready caption with soft CTA, no hashtag spam",
  "slides": [
    {{"headline": "short punchy headline", "body": "1 supporting sentence"}}
  ]
}}
Exactly {slide_count} slides. Headlines under 8 words. Ground claims in the site context.
""".strip()
    response = client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=[
            {"role": "system", "content": "You output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    return json.loads(response.choices[0].message.content or "{}")


def bytes_to_pil(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")
