from django.contrib import admin

from brandgen.models import Brand, PipelineJob, PostSlide, SiteImage, SocialPost


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
    readonly_fields = ("steps", "params", "message", "error_message")
