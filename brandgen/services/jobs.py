"""Background job runners for crawl/generate with progress tracking."""

from __future__ import annotations

import logging
import threading

from django.db import close_old_connections

from brandgen.models import Brand, PipelineJob, SocialPost
from brandgen.services.api_keys import clamp_slide_count, resolve_api_key
from brandgen.services.pipeline import generate_post, ingest_website
from brandgen.services.progress import (
    INGEST_STEPS,
    JobProgress,
    generate_step_defs,
    init_steps,
)

logger = logging.getLogger(__name__)


def create_ingest_job(url: str, *, use_vision: bool = False, job_params: dict | None = None) -> PipelineJob:
    params = {"url": url, "use_vision": use_vision}
    if job_params:
        params.update(job_params)
    return PipelineJob.objects.create(
        job_type=PipelineJob.JobType.INGEST,
        status=PipelineJob.Status.QUEUED,
        steps=init_steps(INGEST_STEPS),
        message="Queued — waiting to crawl",
        params=params,
    )


def create_generate_job(
    brand: Brand,
    *,
    platform: str,
    post_type: str,
    slide_count: int,
    refine_instruction: str = "",
    job_params: dict | None = None,
) -> PipelineJob:
    params = job_params or {}
    using_user_key = params.get("api_key_source") == "user"
    slide_count = clamp_slide_count(slide_count, using_user_key=using_user_key)

    post = SocialPost.objects.create(
        brand=brand,
        platform=platform,
        post_type=post_type,
        status=SocialPost.Status.PENDING,
        slide_count=slide_count,
    )
    merged = {
        "brand_id": str(brand.id),
        "platform": platform,
        "post_type": post_type,
        "slide_count": slide_count,
        "refine_instruction": refine_instruction,
        **params,
    }
    return PipelineJob.objects.create(
        job_type=PipelineJob.JobType.GENERATE,
        status=PipelineJob.Status.QUEUED,
        brand=brand,
        post=post,
        steps=init_steps(generate_step_defs(slide_count)),
        message="Queued — waiting to generate",
        params=merged,
    )


def _run_ingest(job_id) -> None:
    close_old_connections()
    try:
        job = PipelineJob.objects.get(pk=job_id)
        progress = JobProgress(job)
        params = job.params or {}
        api_key, source = resolve_api_key(job_params=params)
        use_vision = bool(params.get("use_vision")) and source == "user"
        ingest_website(
            params.get("url", ""),
            use_vision=use_vision,
            progress=progress,
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest job %s failed", job_id)
        try:
            job = PipelineJob.objects.get(pk=job_id)
            JobProgress(job).fail(str(exc))
        except Exception:  # noqa: BLE001
            pass
    finally:
        close_old_connections()


def _run_generate(job_id) -> None:
    close_old_connections()
    try:
        job = PipelineJob.objects.get(pk=job_id)
        progress = JobProgress(job)
        params = job.params or {}
        api_key, source = resolve_api_key(job_params=params)
        slide_count = clamp_slide_count(
            int(params.get("slide_count") or 1),
            using_user_key=(source == "user"),
        )
        brand = Brand.objects.get(pk=params["brand_id"])
        generate_post(
            brand,
            platform=params.get("platform", SocialPost.Platform.LINKEDIN),
            post_type=params.get("post_type", SocialPost.PostType.SINGLE),
            slide_count=slide_count,
            refine_instruction=params.get("refine_instruction") or "",
            progress=progress,
            existing_post=job.post,
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Generate job %s failed", job_id)
        try:
            job = PipelineJob.objects.get(pk=job_id)
            if job.post_id:
                SocialPost.objects.filter(pk=job.post_id).update(
                    status=SocialPost.Status.FAILED,
                    error_message=str(exc),
                )
            JobProgress(job).fail(str(exc))
        except Exception:  # noqa: BLE001
            pass
    finally:
        close_old_connections()


def start_job_thread(job: PipelineJob) -> None:
    target = _run_ingest if job.job_type == PipelineJob.JobType.INGEST else _run_generate
    thread = threading.Thread(
        target=target,
        args=(job.id,),
        name=f"brandgen-{job.job_type}-{job.id}",
        daemon=True,
    )
    thread.start()
