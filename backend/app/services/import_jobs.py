"""In-memory progress tracking for dataset import jobs."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(*, slug: str, name: str, renderer: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "slug": slug,
            "name": name,
            "renderer": renderer,
            "status": "queued",  # queued | running | done | error
            "phase": "queued",
            "progress": 0,
            "message": "Queued",
            "dataset": None,
            "error": None,
            "updated_at": time.time(),
        }
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = time.time()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def make_progress_cb(job_id: str) -> Callable[[str, int, str], None]:
    def cb(phase: str, progress: int, message: str) -> None:
        update_job(
            job_id,
            status="running",
            phase=phase,
            progress=max(0, min(100, int(progress))),
            message=message,
        )

    return cb
