"""Usage dashboard aggregates."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from brandgen.models import UsageEvent


def dashboard_stats(*, days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = UsageEvent.objects.filter(created_at__gte=since)

    by_type = list(
        qs.values("event_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_billing = list(
        qs.exclude(billing_mode=UsageEvent.BillingMode.UNKNOWN)
        .values("billing_mode")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_domain = list(
        qs.exclude(website_domain="")
        .values("website_domain")
        .annotate(count=Count("id"))
        .order_by("-count")[:15]
    )
    by_platform = list(
        qs.filter(event_type__in=[
            UsageEvent.EventType.GENERATE_STARTED,
            UsageEvent.EventType.GENERATE_COMPLETED,
        ])
        .values("payload__platform")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_post_type = list(
        qs.filter(event_type__in=[
            UsageEvent.EventType.GENERATE_STARTED,
            UsageEvent.EventType.GENERATE_COMPLETED,
        ])
        .values("payload__post_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    daily = list(
        qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    hourly_today = list(
        qs.filter(created_at__gte=timezone.now() - timedelta(hours=24))
        .annotate(hour=TruncHour("created_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )

    unique_sessions = qs.values("visitor_session").distinct().count()
    unique_ips = qs.exclude(ip_address__isnull=True).values("ip_address").distinct().count()
    crawls = qs.filter(
        event_type__in=[
            UsageEvent.EventType.CRAWL_STARTED,
            UsageEvent.EventType.CRAWL_COMPLETED,
        ]
    ).count()
    images_started = qs.filter(event_type=UsageEvent.EventType.GENERATE_STARTED).count()
    images_ok = qs.filter(event_type=UsageEvent.EventType.GENERATE_COMPLETED).count()
    images_fail = qs.filter(event_type=UsageEvent.EventType.GENERATE_FAILED).count()
    recent = qs.select_related("brand", "post")[:40]

    return {
        "days": days,
        "since": since,
        "total_events": qs.count(),
        "unique_sessions": unique_sessions,
        "unique_ips": unique_ips,
        "crawls": crawls,
        "images_started": images_started,
        "images_ok": images_ok,
        "images_fail": images_fail,
        "by_type": by_type,
        "by_billing": by_billing,
        "by_domain": by_domain,
        "by_platform": by_platform,
        "by_post_type": by_post_type,
        "daily": daily,
        "hourly_today": hourly_today,
        "recent": recent,
    }
