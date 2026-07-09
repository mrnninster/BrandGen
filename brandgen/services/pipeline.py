"""Orchestrates crawl → brand kit → generate posts (with live progress)."""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from django.core.files.base import ContentFile
from django.db import transaction

from brandgen.models import Brand, PostSlide, SiteImage, SocialPost
from brandgen.services.compositor import composite_brand_overlay, save_jpeg
from brandgen.services.crawler import CrawlResult, crawl_website
from brandgen.services.media_assets import normalize_image_bytes
from brandgen.services.ocr import evaluate_rendered_text
from brandgen.services.openai_client import (
    bytes_to_pil,
    build_image_prompt,
    generate_captions_and_slides,
    generate_image_bytes,
    label_image_with_vision,
    synthesize_design_system,
)
from brandgen.services.pipeline_settings import is_ocr_enabled
from brandgen.services.progress import JobProgress

logger = logging.getLogger(__name__)


def _download_binary(url: str, timeout: int = 25) -> bytes | None:
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; BrandGenBot/1.0; "
                    "+https://example.com/bot)"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        logger.warning("Download failed %s: %s", url, exc)
        return None


def _save_logo(brand: Brand, crawl: CrawlResult) -> bool:
    """Download logo candidates, convert SVG/ICO, keep the largest usable mark."""
    best = None
    best_area = 0
    best_url = ""

    for logo_url in crawl.logo_candidates:
        data = _download_binary(logo_url)
        if not data:
            continue
        # Favicons are allowed but logos/SVGs preferred via area ranking
        normalized = normalize_image_bytes(
            data,
            hint_url=logo_url,
            prefer_png=True,
            min_size=16,
            svg_width=640,
        )
        if not normalized:
            continue
        area = normalized.width * normalized.height
        # Prefer larger assets; lightly prefer non-favicon URLs
        score = area
        lower = logo_url.lower()
        if "favicon" in lower or lower.endswith(".ico"):
            score *= 0.25
        if "logo" in lower or normalized.source_kind == "svg":
            score *= 1.35
        if score > best_area:
            best_area = score
            best = normalized
            best_url = logo_url

    if not best:
        return False

    name = f"{brand.id}{best.ext}"
    brand.logo.save(name, ContentFile(best.data), save=True)
    logger.info("Saved logo for %s from %s (%sx%s)", brand.id, best_url, best.width, best.height)
    return True


def _save_mshot(brand: Brand) -> bool:
    """Capture a full-page style reference via WordPress mShots."""
    shot_url = f"https://s0.wp.com/mshots/v1/{brand.url}?w=1200"
    data = _download_binary(shot_url, timeout=40)
    if not data or data[:3] == b"GIF":
        return False
    normalized = normalize_image_bytes(data, hint_url=shot_url, prefer_png=False, min_size=40)
    if not normalized:
        # mShots usually returns JPEG — store raw if sniff failed but looks like JPEG
        if data[:3] == b"\xff\xd8\xff":
            brand.screenshot.save(f"{brand.id}.jpg", ContentFile(data), save=True)
            return True
        return False
    brand.screenshot.save(f"{brand.id}{normalized.ext}", ContentFile(normalized.data), save=True)
    return True


def _store_site_image(site_image: SiteImage, data: bytes, source_url: str) -> bool:
    normalized = normalize_image_bytes(
        data,
        hint_url=source_url,
        prefer_png=True,
        min_size=16,
        svg_width=720,
    )
    if not normalized:
        return False
    filename = f"{site_image.brand_id}_{site_image.id}{normalized.ext}"
    site_image.image.save(filename, ContentFile(normalized.data), save=False)
    return True


def ingest_website(
    url: str,
    *,
    use_vision: bool = True,
    max_pages: int = 3,
    progress: JobProgress | None = None,
    api_key: str | None = None,
) -> Brand:
    """Crawl a website, persist brand kit, optionally vision-label images."""
    if progress:
        progress.start()
        progress.begin("crawl", f"Fetching pages from {url}")

    crawl = crawl_website(url, max_pages=max_pages)

    if progress:
        progress.complete(
            "crawl",
            f"Crawled {len(crawl.pages)} page(s) · {len(crawl.images)} images found",
        )
        progress.begin("extract_kit", "Saving colors, fonts, and copy summary")

    with transaction.atomic():
        brand = Brand.objects.create(
            url=crawl.url,
            name=crawl.name,
            colors=crawl.colors,
            fonts=crawl.fonts,
            crawl_summary=crawl.summary_text,
        )

    if progress:
        progress.complete(
            "extract_kit",
            f"{len(crawl.colors)} colors · {len(crawl.fonts)} fonts · {brand.name}",
        )
        progress.begin("logo", "Downloading logo candidates")

    found_logo = _save_logo(brand, crawl)
    if progress:
        progress.complete(
            "logo",
            "Logo saved" if found_logo else "No logo file saved (will rely on vision later)",
        )
        progress.begin("screenshot", "Requesting mShots style reference")

    try:
        got_shot = _save_mshot(brand)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Screenshot capture failed: %s", exc)
        got_shot = False
    if progress:
        progress.complete(
            "screenshot",
            "Screenshot captured" if got_shot else "Screenshot unavailable (continuing)",
        )
        progress.begin("design_system", "Asking GPT for a unique design system")

    design = synthesize_design_system(
        brand_name=brand.name,
        website_url=brand.url,
        colors=brand.colors,
        fonts=brand.fonts,
        site_summary=brand.crawl_summary,
        api_key=api_key,
    )
    brand.design_system = design
    roles = design.get("color_roles") or {}
    ordered = [
        roles.get("primary"),
        roles.get("accent"),
        roles.get("background"),
        roles.get("surface"),
        roles.get("text"),
        roles.get("muted"),
    ]
    merged = [c for c in ordered if c] + [c for c in brand.colors if c not in ordered]
    if merged:
        brand.colors = merged[:8]
    brand.save()

    if progress:
        mood = design.get("mood") or "design system ready"
        progress.complete("design_system", f"Mood: {mood}")
        progress.begin("images", f"Processing up to {min(10, len(crawl.images))} site images")

    image_total = min(10, len(crawl.images))
    saved_count = 0
    for i, img in enumerate(crawl.images[:10]):
        label = img.get("label") or "other"
        if use_vision and label == "other":
            if progress:
                progress.begin(
                    "images",
                    f"Vision-labeling image {i + 1}/{image_total}",
                )
            label = label_image_with_vision(img["url"], img.get("alt", ""), api_key=api_key)
        elif progress and i % 2 == 0:
            progress.begin("images", f"Saving image {i + 1}/{image_total}")

        site_image = SiteImage(
            brand=brand,
            source_url=img["url"],
            alt_text=img.get("alt", "")[:500],
            label=label if label in dict(SiteImage.Label.choices) else SiteImage.Label.OTHER,
        )
        # Need a PK before saving the file name
        site_image.save()

        data = _download_binary(img["url"])
        if data and _store_site_image(site_image, data, img["url"]):
            site_image.save()
            saved_count += 1

            if label == "logo" and (not brand.logo or not brand.logo.name):
                normalized = normalize_image_bytes(
                    data, hint_url=img["url"], prefer_png=True, min_size=24, svg_width=640
                )
                if normalized:
                    brand.logo.save(
                        f"{brand.id}_from_site{normalized.ext}",
                        ContentFile(normalized.data),
                        save=True,
                    )
        # Keep row even without local file — template can fall back to source_url

    if progress:
        progress.complete(
            "images",
            f"Saved {saved_count}/{image_total} displayable site image(s)",
        )
        progress.complete("complete", f"Brand kit ready for {brand.name}")
        progress.succeed(brand=brand, message=f"Brand kit ready for {brand.name}")

    return brand


def generate_post(
    brand: Brand,
    *,
    platform: str = SocialPost.Platform.LINKEDIN,
    post_type: str = SocialPost.PostType.SINGLE,
    slide_count: int | None = None,
    refine_instruction: str = "",
    progress: JobProgress | None = None,
    existing_post: SocialPost | None = None,
    api_key: str | None = None,
) -> SocialPost:
    """Generate a social post with OpenAI images + programmatic logo/headline overlay."""
    if slide_count is None:
        slide_count = 5 if post_type == SocialPost.PostType.CAROUSEL else 1
        if post_type == SocialPost.PostType.QUOTE:
            slide_count = 1

    if existing_post is not None:
        post = existing_post
        post.platform = platform
        post.post_type = post_type
        post.slide_count = slide_count
        post.status = SocialPost.Status.GENERATING
        post.error_message = ""
        post.save(
            update_fields=["platform", "post_type", "slide_count", "status", "error_message", "updated_at"]
        )
    else:
        post = SocialPost.objects.create(
            brand=brand,
            platform=platform,
            post_type=post_type,
            status=SocialPost.Status.GENERATING,
            slide_count=slide_count,
        )

    if progress:
        progress.start()
        progress.job.post = post
        progress.job.brand = brand
        progress.job.save(update_fields=["post", "brand", "updated_at"])
        progress.begin("captions", "Writing captions and slide headlines")

    try:
        design = brand.design_system or {}
        content = generate_captions_and_slides(
            brand_name=brand.name,
            design_system=design,
            post_type=post_type,
            slide_count=slide_count,
            site_summary=brand.crawl_summary,
            api_key=api_key,
        )
        slides_meta = content.get("slides") or []
        while len(slides_meta) < slide_count:
            slides_meta.append(
                {
                    "headline": design.get("sample_hooks", [brand.name])[0],
                    "body": design.get("mood", ""),
                }
            )

        post.caption = content.get("caption", "")
        post.prompt_meta = {
            "design_tokens": design,
            "refine_instruction": refine_instruction,
        }
        post.save(update_fields=["caption", "prompt_meta"])

        if progress:
            progress.complete("captions", "Caption & headlines ready")

        accent = (design.get("color_roles") or {}).get("accent") or brand.accent_color
        text_color = (design.get("color_roles") or {}).get("text") or "#ffffff"
        logo_path = brand.logo.path if brand.logo else None
        ocr_enabled = is_ocr_enabled()

        for idx in range(slide_count):
            meta = slides_meta[idx]
            headline = meta.get("headline") or brand.name
            body = meta.get("body") or ""
            prompt = build_image_prompt(
                brand_name=brand.name,
                design_system=design,
                headline=headline,
                body=body,
                slide_index=idx,
                slide_count=slide_count,
                platform=platform,
                post_type=post_type,
                refine_instruction=refine_instruction,
                force_no_text=not ocr_enabled,
            )
            if idx > 0:
                prompt += (
                    "\nKeep visual continuity with previous slides — same motifs, "
                    "palette roles, lighting, and geometric language."
                )

            if progress:
                progress.begin(
                    f"slide_{idx}",
                    f"OpenAI generating slide {idx + 1}/{slide_count}: {headline}",
                )

            raw = generate_image_bytes(prompt, api_key=api_key)
            pil = bytes_to_pil(raw)
            used_prompt = prompt

            if progress:
                progress.complete(f"slide_{idx}", f"Slide {idx + 1} base image ready")

            if not ocr_enabled:
                if progress:
                    progress.begin(
                        f"overlay_{idx}",
                        f"Compositing logo on slide {idx + 1}",
                    )
                include_headline = False
                overlay_mode = "logo_only"
                ocr_text = ""
                ocr_reason = "ocr_disabled"
            else:
                if progress:
                    progress.begin(
                        f"overlay_{idx}",
                        f"OCR-checking text on slide {idx + 1}",
                    )

                quality = evaluate_rendered_text(pil, headline=headline, brand_name=brand.name)
                include_headline = True
                overlay_mode = "headline_overlay"

                if quality.text_is_usable:
                    include_headline = False
                    overlay_mode = "logo_only"
                    if progress:
                        progress.begin(
                            f"overlay_{idx}",
                            f"Usable AI text ({quality.reason}) — logo overlay only",
                        )
                elif quality.has_text and not quality.text_is_usable:
                    if progress:
                        progress.begin(
                            f"overlay_{idx}",
                            f"OCR text unusable ({quality.reason}) — regenerating without text",
                        )
                    no_text_prompt = build_image_prompt(
                        brand_name=brand.name,
                        design_system=design,
                        headline=headline,
                        body=body,
                        slide_index=idx,
                        slide_count=slide_count,
                        platform=platform,
                        post_type=post_type,
                        refine_instruction=refine_instruction,
                        force_no_text=True,
                    )
                    if idx > 0:
                        no_text_prompt += (
                            "\nKeep visual continuity with previous slides — same motifs, "
                            "palette roles, lighting, and geometric language."
                        )
                    raw = generate_image_bytes(no_text_prompt, api_key=api_key)
                    pil = bytes_to_pil(raw)
                    used_prompt = no_text_prompt
                    include_headline = True
                    overlay_mode = "regenerated_no_text"
                    if progress:
                        progress.begin(
                            f"overlay_{idx}",
                            f"Compositing headline overlay on text-free slide {idx + 1}",
                        )
                else:
                    if progress:
                        progress.begin(
                            f"overlay_{idx}",
                            f"No usable AI text — compositing headline on slide {idx + 1}",
                        )

                ocr_text = quality.raw_text[:2000]
                ocr_reason = quality.reason

            overlay_text = (
                "#ffffff"
                if text_color.lower() in {"#000000", "#111111"}
                else text_color
            )
            composed = composite_brand_overlay(
                pil,
                headline=headline,
                accent_hex=accent,
                text_hex=overlay_text,
                logo_path=logo_path,
                include_headline=include_headline,
                include_logo=True,
            )
            jpeg = save_jpeg(composed)

            slide = PostSlide(
                post=post,
                index=idx,
                headline=headline,
                body=body,
                generation_prompt=used_prompt,
                overlay_mode=overlay_mode,
                ocr_text=ocr_text,
                ocr_reason=ocr_reason,
            )
            slide.image.save(f"{post.id}_{idx}.jpg", ContentFile(jpeg), save=True)

            if progress:
                progress.complete(
                    f"overlay_{idx}",
                    f"Slide {idx + 1} ready ({overlay_mode})",
                )
        post.status = SocialPost.Status.READY
        post.error_message = ""
        post.save(update_fields=["status", "error_message", "updated_at"])

        if progress:
            progress.complete("complete", f"{slide_count} slide(s) ready")
            progress.succeed(brand=brand, post=post, message="Post generated")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Post generation failed")
        post.status = SocialPost.Status.FAILED
        post.error_message = str(exc)
        post.save(update_fields=["status", "error_message", "updated_at"])
        if progress:
            progress.fail(str(exc))
        else:
            raise

    return post


def refine_post(
    post: SocialPost,
    instruction: str,
    *,
    progress: JobProgress | None = None,
    api_key: str | None = None,
) -> SocialPost:
    """Regenerate slides using conversational refine instruction."""
    return generate_post(
        post.brand,
        platform=post.platform,
        post_type=post.post_type,
        slide_count=post.slide_count,
        refine_instruction=instruction,
        progress=progress,
        api_key=api_key,
    )
