import os

from django.apps import AppConfig


class BrandgenConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "brandgen"

    def ready(self) -> None:
        import logging

        from django.conf import settings

        log = logging.getLogger("brandgen.startup")
        media_root = settings.MEDIA_ROOT
        try:
            media_root.mkdir(parents=True, exist_ok=True)
            log.info("Media root ready: %s (writable=%s)", media_root, os.access(media_root, os.W_OK))
        except OSError as exc:
            log.error("Cannot create media root %s: %s", media_root, exc)

        db_engine = settings.DATABASES["default"].get("ENGINE", "")
        log.info(
            "BrandGen ready debug=%s db=%s media=%s",
            settings.DEBUG,
            db_engine.rsplit(".", maxsplit=1)[-1],
            media_root,
        )
