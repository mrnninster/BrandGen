import os
from pathlib import Path

from django.apps import AppConfig


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
        writable = media_root.exists() and os.access(media_root, os.W_OK)

        if not writable:
            try:
                media_root.mkdir(parents=True, exist_ok=True)
                writable = os.access(media_root, os.W_OK)
            except OSError as exc:
                log.error("Media root not writable %s: %s", media_root, exc)

        log.info(
            "Media root: %s (writable=%s ephemeral=%s)",
            media_root,
            writable,
            getattr(settings, "MEDIA_IS_EPHEMERAL", True),
        )
        if on_render:
            from config.media_paths import iter_media_roots

            roots = iter_media_roots(
                primary=media_root,
                base_dir=Path(settings.BASE_DIR),
                on_render=True,
            )
            log.info("Media search paths: %s", ", ".join(str(r) for r in roots))
        if on_render and getattr(settings, "MEDIA_IS_EPHEMERAL", False):
            log.warning(
                "Using ephemeral media storage on Render (%s). "
                "Uploads survive restarts but are cleared on redeploy. "
                "For persistence, attach a disk at /var/data/media (paid plan) "
                "or use S3/R2.",
                media_root,
            )

        db_engine = settings.DATABASES["default"].get("ENGINE", "")
        log.info(
            "BrandGen ready debug=%s on_render=%s db=%s",
            settings.DEBUG,
            on_render,
            db_engine.rsplit(".", maxsplit=1)[-1],
        )
