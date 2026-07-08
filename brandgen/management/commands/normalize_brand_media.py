"""Re-download / convert existing brand logos & site images into displayable files."""

from __future__ import annotations

import logging

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from brandgen.models import Brand, SiteImage
from brandgen.services.media_assets import normalize_image_bytes, sniff_kind

logger = logging.getLogger(__name__)


def _download(url: str) -> bytes | None:
    try:
        resp = requests.get(
            url,
            timeout=25,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; BrandGenBot/1.0)",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None


class Command(BaseCommand):
    help = "Normalize existing brand logos/site images so they display in the brand kit UI."

    def add_arguments(self, parser):
        parser.add_argument("--brand-id", type=str, default="", help="Optional brand UUID")

    def handle(self, *args, **options):
        qs = Brand.objects.all()
        if options["brand_id"]:
            qs = qs.filter(pk=options["brand_id"])

        fixed_logos = 0
        fixed_images = 0

        for brand in qs:
            # Fix logo from disk or by re-fetching image-labeled assets
            logo_fixed = False
            if brand.logo:
                try:
                    raw = brand.logo.read()
                    brand.logo.seek(0)
                    kind = sniff_kind(raw, brand.logo.name)
                    if kind in {"svg", "ico", "unknown"} or brand.logo.name.endswith(".jpg") and raw.lstrip().startswith(b"<"):
                        normalized = normalize_image_bytes(raw, hint_url=brand.logo.name, prefer_png=True)
                        if normalized:
                            brand.logo.save(
                                f"{brand.id}{normalized.ext}",
                                ContentFile(normalized.data),
                                save=True,
                            )
                            fixed_logos += 1
                            logo_fixed = True
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"logo read failed {brand.id}: {exc}")

            if not logo_fixed and not brand.logo:
                logo_img = brand.images.filter(label=SiteImage.Label.LOGO).first()
                if logo_img and logo_img.source_url:
                    data = _download(logo_img.source_url)
                    if data:
                        normalized = normalize_image_bytes(
                            data, hint_url=logo_img.source_url, prefer_png=True, svg_width=640
                        )
                        if normalized:
                            brand.logo.save(
                                f"{brand.id}{normalized.ext}",
                                ContentFile(normalized.data),
                                save=True,
                            )
                            fixed_logos += 1

            for site_image in brand.images.all():
                raw = None
                hint = site_image.source_url
                if site_image.image:
                    try:
                        raw = site_image.image.read()
                        site_image.image.seek(0)
                        hint = site_image.image.name or hint
                    except Exception:  # noqa: BLE001
                        raw = None
                if raw is None and site_image.source_url:
                    raw = _download(site_image.source_url)
                if not raw:
                    continue

                kind = sniff_kind(raw, hint)
                needs = kind in {"svg", "ico", "unknown"} or (
                    site_image.image and site_image.image.name.endswith((".jpg", ".jpeg")) and raw.lstrip().startswith((b"<svg", b"<?xml"))
                )
                if not needs and site_image.image:
                    # Already a proper raster with matching extension
                    continue

                normalized = normalize_image_bytes(
                    raw, hint_url=hint, prefer_png=True, svg_width=720, min_size=16
                )
                if not normalized:
                    continue
                site_image.image.save(
                    f"{brand.id}_{site_image.id}{normalized.ext}",
                    ContentFile(normalized.data),
                    save=True,
                )
                fixed_images += 1

            self.stdout.write(f"Processed {brand.name or brand.url}")

        self.stdout.write(self.style.SUCCESS(f"Fixed {fixed_logos} logos and {fixed_images} site images."))
