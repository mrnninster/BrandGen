"""Live progress helpers for pipeline jobs."""

from __future__ import annotations

import logging
from typing import Any

from brandgen.models import PipelineJob

logger = logging.getLogger(__name__)

# Step keys → human labels for the ingest flow
INGEST_STEPS: list[tuple[str, str]] = [
    ("crawl", "Crawl website"),
    ("extract_kit", "Extract brand kit"),
    ("logo", "Download logo"),
    ("screenshot", "Capture style screenshot"),
    ("design_system", "Synthesize design system"),
    ("images", "Save & label site images"),
    ("complete", "Brand kit ready"),
]


def generate_step_defs(slide_count: int) -> list[tuple[str, str]]:
    steps: list[tuple[str, str]] = [
        ("captions", "Write captions & headlines"),
    ]
    for i in range(slide_count):
        steps.append((f"slide_{i}", f"Generate image · slide {i + 1}/{slide_count}"))
        steps.append((f"overlay_{i}", f"OCR check & composite · slide {i + 1}"))
    steps.append(("complete", "Post ready"))
    return steps


def init_steps(defs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {"key": key, "label": label, "status": "pending", "detail": ""}
        for key, label in defs
    ]


class JobProgress:
    """Mutates a PipelineJob as pipeline stages finish."""

    def __init__(self, job: PipelineJob):
        self.job = job

    def start(self) -> None:
        logger.info("Job %s started (%s)", self.job.id, self.job.job_type)
        self.job.status = PipelineJob.Status.RUNNING
        self.job.percent = 0
        self.job.message = "Starting…"
        self.job.save(update_fields=["status", "percent", "message", "updated_at"])

    def begin(self, key: str, detail: str = "") -> None:
        steps = list(self.job.steps or [])
        for step in steps:
            if step["key"] == key:
                step["status"] = "running"
                step["detail"] = detail
                break
        self.job.steps = steps
        self.job.current_step = key
        self.job.message = detail or next(
            (s["label"] for s in steps if s["key"] == key), key
        )
        logger.info("Job %s step begin: %s — %s", self.job.id, key, self.job.message)
        self.job.save(
            update_fields=["steps", "current_step", "message", "updated_at"]
        )

    def complete(self, key: str, detail: str = "") -> None:
        steps = list(self.job.steps or [])
        total = max(len(steps), 1)
        done = 0
        for step in steps:
            if step["key"] == key:
                step["status"] = "done"
                if detail:
                    step["detail"] = detail
            if step["status"] == "done":
                done += 1
        self.job.steps = steps
        self.job.percent = min(99, int(done / total * 100))
        self.job.message = detail or next(
            (s["label"] for s in steps if s["key"] == key), key
        )
        self.job.current_step = key
        self.job.save(
            update_fields=["steps", "percent", "message", "current_step", "updated_at"]
        )

    def fail_step(self, key: str, detail: str) -> None:
        steps = list(self.job.steps or [])
        for step in steps:
            if step["key"] == key:
                step["status"] = "failed"
                step["detail"] = detail
                break
        self.job.steps = steps
        self.job.current_step = key
        self.job.message = detail
        self.job.save(
            update_fields=["steps", "current_step", "message", "updated_at"]
        )

    def succeed(self, *, brand=None, post=None, message: str = "Done") -> None:
        logger.info("Job %s succeeded: %s", self.job.id, message)
        steps = list(self.job.steps or [])
        for step in steps:
            if step["status"] in {"pending", "running"}:
                step["status"] = "done"
        self.job.steps = steps
        self.job.status = PipelineJob.Status.SUCCEEDED
        self.job.percent = 100
        self.job.message = message
        self.job.current_step = "complete"
        update = ["steps", "status", "percent", "message", "current_step", "updated_at"]
        if brand is not None:
            self.job.brand = brand
            update.append("brand")
        if post is not None:
            self.job.post = post
            update.append("post")
        self.job.save(update_fields=update)

    def fail(self, error: str) -> None:
        logger.error("Job %s failed: %s", self.job.id, error)
        self.job.status = PipelineJob.Status.FAILED
        self.job.error_message = error
        self.job.message = error[:400]
        if self.job.current_step:
            self.fail_step(self.job.current_step, error[:300])
        self.job.save(
            update_fields=["status", "error_message", "message", "updated_at"]
        )
