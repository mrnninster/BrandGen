"""Anonymous usage tracking — when, where, and what (never API keys)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from django.http import HttpRequest
from django.utils import timezone

from brandgen.models import Brand, PipelineJob, SocialPost, UsageEvent

logger = logging.getLogger(__name__)

SENSITIVE_PARAM_KEYS = frozenset(
    {"user_api_key", "api_key", "openai_api_key", "authorization", "password", "token"}
)


def get_client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    ip = request.META.get("REMOTE_ADDR")
    return ip[:45] if ip else None


def ensure_visitor_session(request: HttpRequest) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or "anonymous"


def request_context(request: HttpRequest) -> dict:
    """Attach to job params so background workers can log completion."""
    return {
        "visitor_session": ensure_visitor_session(request),
        "ip_address": get_client_ip(request),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:500],
        "request_path": request.path,
    }


def extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return ""


def _billing_mode_from_params(params: dict | None) -> str:
    if not params:
        return UsageEvent.BillingMode.UNKNOWN
    source = params.get("api_key_source")
    if source == "user":
        return UsageEvent.BillingMode.USER
    if source == "server":
        return UsageEvent.BillingMode.DEMO
    return UsageEvent.BillingMode.UNKNOWN


def _safe_payload(data: dict | None) -> dict:
    if not data:
        return {}
    clean: dict = {}
    for key, value in data.items():
        if key in SENSITIVE_PARAM_KEYS:
            continue
        if "key" in key.lower() and key not in {"api_key_source"}:
            continue
        if isinstance(value, str) and len(value) > 500:
            value = value[:500] + "…"
        clean[key] = value
    return clean


def track(
    request: HttpRequest | None,
    event_type: str,
    *,
    billing_mode: str | None = None,
    website_url: str = "",
    brand: Brand | None = None,
    post: SocialPost | None = None,
    job: PipelineJob | None = None,
    payload: dict | None = None,
    visitor_session: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
    path: str = "",
) -> UsageEvent | None:
    """Record a usage event. Never pass API keys in payload."""
    try:
        if request is not None:
            visitor_session = ensure_visitor_session(request)
            ip_address = get_client_ip(request)
            user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:500]
            path = request.path

        domain = extract_domain(website_url)
        if not domain and brand and brand.url:
            domain = extract_domain(brand.url)
            website_url = website_url or brand.url

        meta = _safe_payload(payload)
        if brand:
            meta.setdefault("brand_name", brand.name)
            meta.setdefault("brand_id", str(brand.id))
        if post:
            meta.setdefault("post_type", post.post_type)
            meta.setdefault("platform", post.platform)
            meta.setdefault("slide_count", post.slide_count)

        event = UsageEvent.objects.create(
            visitor_session=visitor_session or "unknown",
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            path=path,
            billing_mode=billing_mode or UsageEvent.BillingMode.UNKNOWN,
            website_url=website_url[:500],
            website_domain=domain[:200],
            brand=brand,
            post=post,
            job=job,
            payload=meta,
        )
        return event
    except Exception as exc:  # noqa: BLE001
        logger.warning("Usage tracking failed for %s: %s", event_type, exc)
        return None


def track_job_started(
    request: HttpRequest,
    job: PipelineJob,
    *,
    website_url: str = "",
    billing_mode: str | None = None,
    extra: dict | None = None,
) -> None:
    params = job.params or {}
    if billing_mode is None:
        billing_mode = _billing_mode_from_params(params)

    if job.job_type == PipelineJob.JobType.INGEST:
        event_type = UsageEvent.EventType.CRAWL_STARTED
        url = website_url or params.get("url", "")
        payload = {
            "use_vision": bool(params.get("use_vision")),
            **(extra or {}),
        }
    else:
        event_type = UsageEvent.EventType.GENERATE_STARTED
        url = website_url or (job.brand.url if job.brand_id else "")
        payload = {
            "platform": params.get("platform"),
            "post_type": params.get("post_type"),
            "slide_count": params.get("slide_count"),
            "refine": bool(params.get("refine_instruction")),
            **(extra or {}),
        }

    track(
        request,
        event_type,
        billing_mode=billing_mode,
        website_url=url,
        brand=job.brand,
        post=job.post,
        job=job,
        payload=payload,
    )


def track_job_finished(job: PipelineJob, *, success: bool, error: str = "") -> None:
    """Called from background workers when a pipeline job completes."""
    params = job.params or {}
    job.refresh_from_db()

    billing_mode = _billing_mode_from_params(params)
    visitor_session = params.get("visitor_session", "unknown")
    ip_address = params.get("ip_address")
    user_agent = params.get("user_agent", "")
    path = params.get("request_path", "")

    duration_s = None
    if job.created_at:
        duration_s = round((timezone.now() - job.created_at).total_seconds(), 1)

    if job.job_type == PipelineJob.JobType.INGEST:
        event_type = (
            UsageEvent.EventType.CRAWL_COMPLETED
            if success
            else UsageEvent.EventType.CRAWL_FAILED
        )
        url = params.get("url", "")
        payload = {
            "use_vision": bool(params.get("use_vision")),
            "duration_seconds": duration_s,
            "status": "succeeded" if success else "failed",
            "error": error[:300] if error else "",
            "brand_name": job.brand.name if job.brand_id else "",
        }
    else:
        event_type = (
            UsageEvent.EventType.GENERATE_COMPLETED
            if success
            else UsageEvent.EventType.GENERATE_FAILED
        )
        url = job.brand.url if job.brand_id else ""
        payload = {
            "platform": params.get("platform"),
            "post_type": params.get("post_type"),
            "slide_count": params.get("slide_count"),
            "refine": bool(params.get("refine_instruction")),
            "duration_seconds": duration_s,
            "status": "succeeded" if success else "failed",
            "error": error[:300] if error else "",
            "brand_name": job.brand.name if job.brand_id else "",
        }

    track(
        None,
        event_type,
        billing_mode=billing_mode,
        website_url=url,
        brand=job.brand,
        post=job.post,
        job=job,
        payload=payload,
        visitor_session=visitor_session,
        ip_address=ip_address,
        user_agent=user_agent,
        path=path,
    )
