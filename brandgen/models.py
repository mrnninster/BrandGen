import json
import uuid

from django.db import models
from django.utils import timezone


class Brand(models.Model):
    """A crawled website and its extracted brand kit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    url = models.URLField(max_length=500)
    name = models.CharField(max_length=200, blank=True)
    colors = models.JSONField(default=list, blank=True)
    fonts = models.JSONField(default=list, blank=True)
    design_system = models.JSONField(default=dict, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    screenshot = models.ImageField(upload_to="screenshots/", blank=True, null=True)
    crawl_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or self.url

    @property
    def primary_color(self) -> str:
        if self.colors:
            return self.colors[0]
        return "#111111"

    @property
    def accent_color(self) -> str:
        if len(self.colors) > 1:
            return self.colors[1]
        return self.primary_color

    def palette_css(self) -> str:
        return ", ".join(self.colors[:6]) if self.colors else "—"

    def design_system_json(self) -> str:
        return json.dumps(self.design_system or {}, indent=2)


class SiteImage(models.Model):
    """An image scraped from the brand website, optionally labeled by vision."""

    class Label(models.TextChoices):
        LOGO = "logo", "Logo"
        PRODUCT = "product", "Product"
        PHOTO = "photo", "Photo"
        ICON = "icon", "Icon"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(Brand, related_name="images", on_delete=models.CASCADE)
    source_url = models.URLField(max_length=1000)
    image = models.ImageField(upload_to="scraped/", blank=True, null=True)
    label = models.CharField(max_length=20, choices=Label.choices, default=Label.OTHER)
    alt_text = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.label}: {self.source_url[:60]}"

    @property
    def display_url(self) -> str:
        """Prefer local normalized media; fall back to original source URL."""
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return self.source_url


class SocialPost(models.Model):
    """A generated social media post (single image or carousel slides)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        APPROVED = "approved", "Approved"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    class Platform(models.TextChoices):
        LINKEDIN = "linkedin", "LinkedIn"
        INSTAGRAM = "instagram", "Instagram"
        FACEBOOK = "facebook", "Facebook"
        X = "x", "X / Twitter"

    class PostType(models.TextChoices):
        SINGLE = "single", "Single image"
        CAROUSEL = "carousel", "Carousel"
        QUOTE = "quote", "Quote card"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(Brand, related_name="posts", on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.LINKEDIN)
    post_type = models.CharField(max_length=20, choices=PostType.choices, default=PostType.SINGLE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    caption = models.TextField(blank=True)
    slide_count = models.PositiveSmallIntegerField(default=1)
    prompt_meta = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.brand} — {self.post_type} ({self.status})"

    def design_tokens_json(self) -> str:
        return json.dumps(self.prompt_meta.get("design_tokens", {}), indent=2)


class PostSlide(models.Model):
    """One slide / frame of a social post."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(SocialPost, related_name="slides", on_delete=models.CASCADE)
    index = models.PositiveSmallIntegerField(default=0)
    headline = models.CharField(max_length=300, blank=True)
    body = models.TextField(blank=True)
    image = models.ImageField(upload_to="generated/", blank=True, null=True)
    generation_prompt = models.TextField(blank=True)
    overlay_mode = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="How typography was applied: logo_only | headline_overlay | regenerated_no_text",
    )
    ocr_text = models.TextField(blank=True)
    ocr_reason = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["index"]

    def __str__(self) -> str:
        return f"Slide {self.index} of {self.post_id}"

    @property
    def download_name(self) -> str:
        brand = getattr(self.post, "brand", None)
        brand_slug = (brand.name if brand else "post").replace(" ", "-")[:40]
        return f"{brand_slug}-slide-{self.index + 1}.jpg"

class PipelineJob(models.Model):
    """Tracks crawl → kit → image generation progress for the live UI."""

    class JobType(models.TextChoices):
        INGEST = "ingest", "Crawl & brand kit"
        GENERATE = "generate", "Generate images"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type = models.CharField(max_length=20, choices=JobType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    percent = models.PositiveSmallIntegerField(default=0)
    current_step = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=400, blank=True)
    steps = models.JSONField(default=list, blank=True)
    params = models.JSONField(default=dict, blank=True)
    brand = models.ForeignKey(
        Brand, null=True, blank=True, related_name="jobs", on_delete=models.SET_NULL
    )
    post = models.ForeignKey(
        SocialPost, null=True, blank=True, related_name="jobs", on_delete=models.SET_NULL
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.job_type} [{self.status}] {self.percent}%"

    def to_progress_dict(self) -> dict:
        return {
            "id": str(self.id),
            "job_type": self.job_type,
            "status": self.status,
            "percent": self.percent,
            "current_step": self.current_step,
            "message": self.message,
            "steps": self.steps,
            "error_message": self.error_message,
            "brand_id": str(self.brand_id) if self.brand_id else None,
            "post_id": str(self.post_id) if self.post_id else None,
            "redirect_url": self.redirect_url(),
        }

    def redirect_url(self) -> str | None:
        if self.status != self.Status.SUCCEEDED:
            return None
        if self.job_type == self.JobType.INGEST and self.brand_id:
            return f"/brands/{self.brand_id}/"
        if self.job_type == self.JobType.GENERATE and self.post_id:
            return f"/posts/{self.post_id}/"
        return None


class UsageEvent(models.Model):
    """Anonymous usage analytics — no API keys, no user accounts."""

    class EventType(models.TextChoices):
        CRAWL_STARTED = "crawl_started", "Crawl started"
        CRAWL_COMPLETED = "crawl_completed", "Crawl completed"
        CRAWL_FAILED = "crawl_failed", "Crawl failed"
        GENERATE_STARTED = "generate_started", "Generate started"
        GENERATE_COMPLETED = "generate_completed", "Generate completed"
        GENERATE_FAILED = "generate_failed", "Generate failed"
        POST_APPROVED = "post_approved", "Post approved"
        POST_SKIPPED = "post_skipped", "Post skipped"
        REGENERATE_STARTED = "regenerate_started", "Regenerate started"
        REFINE_STARTED = "refine_started", "Refine started"
        API_KEY_SET = "api_key_set", "Visitor API key set"
        API_KEY_CLEARED = "api_key_cleared", "Visitor API key cleared"
        SLIDE_DOWNLOAD = "slide_download", "Slide downloaded"

    class BillingMode(models.TextChoices):
        USER = "user", "Visitor key"
        DEMO = "demo", "Demo / server key"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor_session = models.CharField(max_length=64, db_index=True)
    event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=500, blank=True)
    path = models.CharField(max_length=300, blank=True)

    billing_mode = models.CharField(
        max_length=20,
        choices=BillingMode.choices,
        default=BillingMode.UNKNOWN,
        db_index=True,
    )
    website_url = models.URLField(max_length=500, blank=True)
    website_domain = models.CharField(max_length=200, blank=True, db_index=True)

    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    post = models.ForeignKey(SocialPost, null=True, blank=True, on_delete=models.SET_NULL)
    job = models.ForeignKey(PipelineJob, null=True, blank=True, on_delete=models.SET_NULL)

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "event_type"]),
            models.Index(fields=["website_domain", "-created_at"]),
        ]

    def __str__(self) -> str:
        who = self.website_domain or self.visitor_session[:8]
        return f"{self.event_type} · {who} · {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def summary(self) -> str:
        p = self.payload or {}
        parts = []
        if self.website_domain:
            parts.append(self.website_domain)
        if p.get("brand_name"):
            parts.append(p["brand_name"])
        if p.get("platform"):
            parts.append(p["platform"])
        if p.get("post_type"):
            parts.append(p["post_type"])
        if p.get("slide_count"):
            parts.append(f"{p['slide_count']} slide(s)")
        if p.get("status"):
            parts.append(p["status"])
        return " · ".join(parts) or self.get_event_type_display()
