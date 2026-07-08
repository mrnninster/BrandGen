from django.contrib import admin
from django.shortcuts import render
from django.urls import path, reverse

from brandgen.models import Brand, PipelineJob, PostSlide, SiteImage, SocialPost, UsageEvent
from brandgen.services.usage_stats import dashboard_stats


class SiteImageInline(admin.TabularInline):
    model = SiteImage
    extra = 0
    readonly_fields = ("source_url", "label", "alt_text")


class PostSlideInline(admin.TabularInline):
    model = PostSlide
    extra = 0
    readonly_fields = ("index", "headline", "image")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "created_at")
    search_fields = ("name", "url")
    inlines = [SiteImageInline]


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = ("brand", "post_type", "platform", "status", "created_at")
    list_filter = ("status", "platform", "post_type")
    inlines = [PostSlideInline]


@admin.register(PipelineJob)
class PipelineJobAdmin(admin.ModelAdmin):
    list_display = ("job_type", "status", "percent", "current_step", "created_at")
    list_filter = ("job_type", "status")
    readonly_fields = ("steps", "message", "error_message")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        # Never expose raw job params — may contain visitor API keys
        fields.append("params")
        return fields


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    change_list_template = "admin/brandgen/usageevent/change_list.html"

    list_display = (
        "created_at",
        "event_type",
        "website_domain",
        "summary",
        "billing_mode",
        "ip_address",
        "visitor_session",
    )
    list_filter = ("event_type", "billing_mode", "created_at")
    search_fields = ("website_domain", "website_url", "visitor_session", "ip_address", "payload")
    readonly_fields = (
        "visitor_session",
        "event_type",
        "created_at",
        "ip_address",
        "user_agent",
        "path",
        "billing_mode",
        "website_url",
        "website_domain",
        "brand",
        "post",
        "job",
        "payload",
    )
    date_hierarchy = "created_at"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "dashboard/",
                self.admin_site.admin_view(self.analytics_dashboard),
                name="brandgen_usage_dashboard",
            ),
        ]
        return custom + urls

    def analytics_dashboard(self, request):
        days = int(request.GET.get("days", 7))
        days = max(1, min(days, 90))
        stats = dashboard_stats(days=days)
        return render(
            request,
            "brandgen/usage_dashboard.html",
            {
                "stats": stats,
                "days": days,
                "from_admin": True,
                "admin_usage_url": reverse("admin:brandgen_usageevent_changelist"),
            },
        )

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def summary(self, obj: UsageEvent) -> str:
        return obj.summary

    summary.short_description = "What"


admin.site.site_header = "BrandGen Admin"
admin.site.site_title = "BrandGen Admin"
admin.site.index_title = "Site administration"
