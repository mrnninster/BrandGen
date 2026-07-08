from django import forms
from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from brandgen.models import Brand, PipelineJob, PostSlide, SocialPost
from brandgen.services.api_keys import (
    clamp_slide_count,
    clear_user_api_key,
    get_user_api_key,
    job_api_params,
    session_key_status,
    set_user_api_key,
)
from brandgen.services.jobs import (
    create_generate_job,
    create_ingest_job,
    start_job_thread,
)


class CrawlForm(forms.Form):
    url = forms.CharField(
        label="Website URL",
        widget=forms.TextInput(
            attrs={
                "placeholder": "https://eprovement.com",
                "class": "input",
                "autocomplete": "url",
            }
        ),
    )
    use_vision = forms.BooleanField(
        required=False,
        initial=False,
        label="Label images with GPT vision (requires your API key)",
    )

    def clean_url(self) -> str:
        raw = self.cleaned_data["url"].strip()
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return raw


class GenerateForm(forms.Form):
    platform = forms.ChoiceField(choices=SocialPost.Platform.choices, initial=SocialPost.Platform.LINKEDIN)
    post_type = forms.ChoiceField(choices=SocialPost.PostType.choices, initial=SocialPost.PostType.CAROUSEL)
    slide_count = forms.IntegerField(min_value=1, max_value=8, initial=5, required=False)


class RefineForm(forms.Form):
    instruction = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "input",
                "placeholder": "e.g. Make the 3D object glassier and pull accent teal into the background shapes.",
            }
        ),
        label="Refine in plain language",
    )


class ApiKeyForm(forms.Form):
    api_key = forms.CharField(
        label="OpenAI API key",
        widget=forms.PasswordInput(
            attrs={
                "class": "input",
                "placeholder": "sk-…",
                "autocomplete": "off",
            }
        ),
    )


def _job_params(request: HttpRequest) -> dict:
    return job_api_params(request.session)


def _resolve_slide_count(form: GenerateForm, request: HttpRequest, post_type: str) -> int:
    using_user = bool(get_user_api_key(request.session))
    if post_type != SocialPost.PostType.CAROUSEL:
        return 1
    raw = form.cleaned_data.get("slide_count") or (5 if using_user else 1)
    return clamp_slide_count(raw, using_user_key=using_user)


@require_http_methods(["GET", "POST"])
def home(request: HttpRequest) -> HttpResponse:
    form = CrawlForm(request.POST or None)
    brands = Brand.objects.all()[:12]
    key_status = session_key_status(request.session)

    if request.method == "POST" and form.is_valid():
        if not key_status["can_generate"]:
            messages.error(
                request,
                "No API key available. Add your OpenAI key in the header to continue.",
            )
        else:
            use_vision = form.cleaned_data.get("use_vision", False)
            if use_vision and not key_status["has_user_key"]:
                use_vision = False
            job = create_ingest_job(
                form.cleaned_data["url"],
                use_vision=use_vision,
                job_params=_job_params(request),
            )
            start_job_thread(job)
            return redirect("job_progress", job_id=job.id)

    return render(
        request,
        "brandgen/home.html",
        {"form": form, "brands": brands, "api_key": key_status},
    )


def brand_detail(request: HttpRequest, brand_id) -> HttpResponse:
    brand = get_object_or_404(Brand.objects.prefetch_related("images", "posts"), pk=brand_id)
    form = GenerateForm(request.POST or None)
    key_status = session_key_status(request.session)

    if request.method == "POST" and form.is_valid():
        if not key_status["can_generate"]:
            messages.error(
                request,
                "No API key available. Add your OpenAI key in the header to generate images.",
            )
        else:
            post_type = form.cleaned_data["post_type"]
            slide_count = _resolve_slide_count(form, request, post_type)
            job = create_generate_job(
                brand,
                platform=form.cleaned_data["platform"],
                post_type=post_type,
                slide_count=slide_count,
                job_params=_job_params(request),
            )
            start_job_thread(job)
            return redirect("job_progress", job_id=job.id)

    return render(
        request,
        "brandgen/brand_detail.html",
        {
            "brand": brand,
            "form": form,
            "posts": brand.posts.all()[:20],
            "api_key": key_status,
        },
    )


def post_detail(request: HttpRequest, post_id) -> HttpResponse:
    post = get_object_or_404(
        SocialPost.objects.select_related("brand").prefetch_related("slides"),
        pk=post_id,
    )
    refine_form = RefineForm()
    return render(
        request,
        "brandgen/post_detail.html",
        {
            "post": post,
            "refine_form": refine_form,
            "slides": post.slides.all(),
            "api_key": session_key_status(request.session),
        },
    )


@require_POST
def post_action(request: HttpRequest, post_id) -> HttpResponse:
    post = get_object_or_404(SocialPost.objects.select_related("brand"), pk=post_id)
    action = request.POST.get("action")
    key_status = session_key_status(request.session)

    if action == "approve":
        post.status = SocialPost.Status.APPROVED
        post.save(update_fields=["status", "updated_at"])
        messages.success(request, "Post approved.")
        return redirect("brand_detail", brand_id=post.brand_id)
    if action == "skip":
        post.status = SocialPost.Status.SKIPPED
        post.save(update_fields=["status", "updated_at"])
        messages.info(request, "Post skipped — back to brand kit.")
        return redirect("brand_detail", brand_id=post.brand_id)
    if action in {"regenerate", "refine"}:
        if not key_status["can_generate"]:
            messages.error(request, "Add your OpenAI API key in the header to regenerate.")
            return redirect("post_detail", post_id=post.id)

    if action == "regenerate":
        slide_count = clamp_slide_count(
            post.slide_count,
            using_user_key=key_status["has_user_key"],
        )
        job = create_generate_job(
            post.brand,
            platform=post.platform,
            post_type=post.post_type,
            slide_count=slide_count,
            job_params=_job_params(request),
        )
        start_job_thread(job)
        return redirect("job_progress", job_id=job.id)
    if action == "refine":
        form = RefineForm(request.POST)
        if form.is_valid():
            slide_count = clamp_slide_count(
                post.slide_count,
                using_user_key=key_status["has_user_key"],
            )
            job = create_generate_job(
                post.brand,
                platform=post.platform,
                post_type=post.post_type,
                slide_count=slide_count,
                refine_instruction=form.cleaned_data["instruction"],
                job_params=_job_params(request),
            )
            start_job_thread(job)
            return redirect("job_progress", job_id=job.id)
        messages.error(request, "Enter a refine instruction.")
    return redirect("post_detail", post_id=post.id)


@require_POST
def api_key_set(request: HttpRequest) -> HttpResponse:
    form = ApiKeyForm(request.POST)
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("home")
    if form.is_valid():
        try:
            set_user_api_key(request.session, form.cleaned_data["api_key"])
            messages.success(
                request,
                "Your OpenAI API key is saved for this browser session. "
                "Unlimited generations until you close the tab.",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Enter a valid OpenAI API key.")
    return redirect(next_url)


@require_POST
def api_key_clear(request: HttpRequest) -> HttpResponse:
    clear_user_api_key(request.session)
    messages.info(request, "Your API key was removed. Demo mode: 1 image per generation run.")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("home")
    return redirect(next_url)


@require_GET
def slide_download(request: HttpRequest, slide_id) -> HttpResponse:
    slide = get_object_or_404(PostSlide.objects.select_related("post", "post__brand"), pk=slide_id)
    if not slide.image:
        return HttpResponseNotFound("Slide image not found")
    return FileResponse(
        slide.image.open("rb"),
        as_attachment=True,
        filename=slide.download_name,
        content_type="image/jpeg",
    )


def job_progress(request: HttpRequest, job_id) -> HttpResponse:
    job = get_object_or_404(PipelineJob, pk=job_id)
    title = (
        "Extracting brand kit"
        if job.job_type == PipelineJob.JobType.INGEST
        else "Generating images"
    )
    return render(
        request,
        "brandgen/progress.html",
        {
            "job": job,
            "title": title,
            "progress_url": reverse("job_progress_api", kwargs={"job_id": job.id}),
            "api_key": session_key_status(request.session),
        },
    )


@require_GET
def job_progress_api(request: HttpRequest, job_id) -> JsonResponse:
    job = get_object_or_404(PipelineJob, pk=job_id)
    return JsonResponse(job.to_progress_dict())
