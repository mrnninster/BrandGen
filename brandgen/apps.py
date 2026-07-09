import os
from pathlib import Path

from django.apps import AppConfig

RENDER_MEDIA_ROOT = Path("/var/data/media")


class BrandgenConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "brandgen"

    def ready(self) -> None:
        import logging

        try:
            self._log_startup()
        except Exception as exc:  # noqa: BLE001 — never block deploy on startup checks
            logging.getLogger("brandgen.startup").warning(
                "Startup checks skipped: %s", exc
            )

    def _log_startup(self) -> None:
        import logging

        from django.conf import settings

        log = logging.getLogger("brandgen.startup")
        media_root = Path(settings.MEDIA_ROOT)
        on_render = os.environ.get("RENDER") == "true"

        if media_root.exists():
            log.info(
                "Media root ready: %s (writable=%s)",
                media_root,
                os.access(media_root, os.W_OK),
            )
        else:
            try:
                media_root.mkdir(parents=True, exist_ok=True)
                log.info(
                    "Media root ready: %s (writable=%s)",
                    media_root,
                    os.access(media_root, os.W_OK),
                )
            except OSError as exc:
                if on_render and media_root == RENDER_MEDIA_ROOT:
                    log.warning(
                        "Media root %s not mounted yet (%s) — expected during build; "
                        "disk mounts at runtime on Render.",
                        media_root,
                        exc,
                    )
                else:
                    log.error("Cannot create media root %s: %s", media_root, exc)

        db_engine = settings.DATABASES["default"].get("ENGINE", "")
        log.info(
            "BrandGen ready debug=%s on_render=%s db=%s media=%s",
            settings.DEBUG,
            on_render,
            db_engine.rsplit(".", maxsplit=1)[-1],
            media_root,
        )
        if on_render and media_root != RENDER_MEDIA_ROOT:
            log.warning(
                "Render deploy should use MEDIA_ROOT=/var/data/media with a mounted disk; "
                "current path may be ephemeral: %s",
                media_root,
            )
