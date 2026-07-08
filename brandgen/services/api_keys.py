"""Session-scoped OpenAI API keys — no user accounts required."""

from __future__ import annotations

from django.conf import settings

SESSION_KEY = "user_openai_api_key"


def is_valid_openai_key(key: str) -> bool:
    key = (key or "").strip()
    return key.startswith("sk-") and len(key) >= 20


def get_user_api_key(session) -> str | None:
    key = session.get(SESSION_KEY)
    if key and is_valid_openai_key(key):
        return key.strip()
    return None


def set_user_api_key(session, key: str) -> None:
    key = key.strip()
    if not is_valid_openai_key(key):
        raise ValueError("Invalid OpenAI API key format (expected sk-…).")
    session[SESSION_KEY] = key
    session.modified = True


def clear_user_api_key(session) -> None:
    session.pop(SESSION_KEY, None)
    session.modified = True


def key_hint(key: str | None) -> str:
    if not key or len(key) < 8:
        return ""
    return f"…{key[-4:]}"


def session_key_status(session) -> dict:
    user_key = get_user_api_key(session)
    has_user = bool(user_key)
    server_configured = bool(
        settings.OPENAI_API_KEY and not str(settings.OPENAI_API_KEY).startswith("sk-your")
    )
    return {
        "has_user_key": has_user,
        "is_demo_mode": not has_user,
        "key_hint": key_hint(user_key),
        "demo_max_slides": settings.DEMO_MAX_SLIDES,
        "server_key_available": server_configured,
        "can_generate": has_user or server_configured,
    }


def resolve_api_key(*, session=None, job_params: dict | None = None) -> tuple[str, str]:
    """
    Return (api_key, source) where source is 'user' or 'server'.
    Job params take precedence (background threads have no session).
    """
    params = job_params or {}
    if params.get("user_api_key") and is_valid_openai_key(params["user_api_key"]):
        return params["user_api_key"].strip(), "user"
    if session is not None:
        user_key = get_user_api_key(session)
        if user_key:
            return user_key, "user"
    server = settings.OPENAI_API_KEY
    if not server or str(server).startswith("sk-your"):
        raise RuntimeError(
            "No OpenAI API key available. Add your key in the header, "
            "or configure OPENAI_API_KEY on the server."
        )
    return server, "server"


def clamp_slide_count(slide_count: int, *, using_user_key: bool) -> int:
    slide_count = max(1, int(slide_count or 1))
    if using_user_key:
        return min(slide_count, 8)
    return min(slide_count, settings.DEMO_MAX_SLIDES)


def job_api_params(session) -> dict:
    """Snapshot session key into job params for background workers."""
    user_key = get_user_api_key(session)
    if user_key:
        return {"user_api_key": user_key, "api_key_source": "user"}
    return {"user_api_key": None, "api_key_source": "server"}
