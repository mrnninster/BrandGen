"""Pick a writable MEDIA_ROOT — Render free tier has no /var/data disk."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_media_root(*, base_dir: Path, on_render: bool) -> tuple[Path, bool]:
    """
    Return (media_root, is_ephemeral).

    Tries, in order:
    1. MEDIA_ROOT env (if writable)
    2. /var/data/media — Render persistent disk (paid + disk attached)
    3. /tmp/brandgen-media — always writable on Render, cleared on restart
    4. <project>/media — writable at runtime, cleared on redeploy
    """
    candidates: list[Path] = []
    explicit = os.environ.get("MEDIA_ROOT")
    if explicit:
        candidates.append(Path(explicit))
    if on_render:
        candidates.extend(
            [
                Path("/var/data/media"),
                base_dir / "media",
                Path("/tmp/brandgen-media"),
            ]
        )
    else:
        candidates.append(base_dir / "media")

    seen: set[str] = set()
    ordered: list[Path] = []
    for path in candidates:
        key = str(path.resolve() if path.exists() else path)
        if key not in seen:
            seen.add(key)
            ordered.append(path)

    for path in ordered:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                if path == Path("/var/data/media"):
                    ephemeral = False
                elif on_render:
                    ephemeral = True
                else:
                    ephemeral = False
                return path, ephemeral
        except OSError:
            continue

    fallback = ordered[-1]
    return fallback, True


def iter_media_roots(*, primary: Path, base_dir: Path, on_render: bool) -> list[Path]:
    """All directories to search when serving a previously uploaded file."""
    candidates: list[Path] = [primary]
    if on_render:
        candidates.extend(
            [
                Path("/var/data/media"),
                base_dir / "media",
                Path("/tmp/brandgen-media"),
            ]
        )
    else:
        candidates.append(base_dir / "media")

    seen: set[str] = set()
    roots: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        roots.append(path)
    return roots or [primary]

