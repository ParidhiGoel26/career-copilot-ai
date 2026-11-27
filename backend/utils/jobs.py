"""Async job queue: in-process thread pool or Redis+RQ.

API contract stays the same: submit(...) -> job_id, get(job_id) -> Job.
JOB_BACKEND=memory|redis (default memory unless REDIS_URL is set and backend=redis).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from utils import metrics
from utils.job_tasks import execute_task

logger = logging.getLogger("careerai.jobs")

TERMINAL = frozenset({"done", "failed"})
QUEUE_NAME = "careerai"


@dataclass
class Job:
    id: str
    job_type: str
    user_id: str | None
    status: str = "queued"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self, include_result: bool = True) -> dict:
        data = {
            "job_id": self.id,
            "type": self.job_type,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_result and self.status == "done":
            data["result"] = self.result
        return data


def _job_backend() -> str:
    explicit = (os.getenv("JOB_BACKEND") or "").strip().lower()
    if explicit in ("memory", "redis"):
        return explicit
    if os.getenv("REDIS_URL", "").strip():
        return "redis"
    return "memory"


class MemoryJobManager:
    def __init__(self, max_workers: int = 2):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="careerai-job"
        )

    def submit(self, job_type: str, payload: dict, *, user_id: str | None = None) -> str:
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, job_type=job_type, user_id=user_id)
        with self._lock:
            self._jobs[job_id] = job
        metrics.incr("jobs_queued")
        self._executor.submit(self._run, job_id, job_type, payload)
        return job_id

    def _run(self, job_id: str, job_type: str, payload: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.updated_at = time.time()
        metrics.incr("jobs_running")
        try:
            result = execute_task(job_type, payload)
            with self._lock:
                job = self._jobs[job_id]
                job.result = result
                job.status = "done"
                job.updated_at = time.time()
            metrics.incr("jobs_done")
        except Exception as exc:
            logger.exception("memory job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = str(exc) or traceback.format_exc(limit=3)
                job.updated_at = time.time()
            metrics.incr("jobs_failed")

    def get(self, job_id: str, *, user_id: str | None = None) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if user_id is not None and job.user_id and job.user_id != user_id:
                return None
            return job

    def reset_for_tests(self) -> None:
        with self._lock:
            self._jobs.clear()


class RedisJobManager:
    """Job metadata in Redis hashes; work executed by RQ workers."""

    def __init__(self, redis_url: str):
        from redis import Redis
        from rq import Queue

        self._redis = Redis.from_url(redis_url)
        self._queue = Queue(QUEUE_NAME, connection=self._redis)

    def _key(self, job_id: str) -> str:
        return f"careerai:job:{job_id}"

    def submit(self, job_type: str, payload: dict, *, user_id: str | None = None) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        meta = {
            "id": job_id,
            "type": job_type,
            "user_id": user_id or "",
            "status": "queued",
            "result": "",
            "error": "",
            "created_at": str(now),
            "updated_at": str(now),
            "payload": json.dumps(payload),
        }
        self._redis.hset(self._key(job_id), mapping=meta)
        self._redis.expire(self._key(job_id), 86400)
        metrics.incr("jobs_queued")
        # Import string path for RQ serialization
        self._queue.enqueue(
            "utils.jobs.process_redis_job",
            job_id,
            job_timeout=600,
            result_ttl=3600,
            failure_ttl=86400,
        )
        return job_id

    def get(self, job_id: str, *, user_id: str | None = None) -> Job | None:
        data = self._redis.hgetall(self._key(job_id))
        if not data:
            return None
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in data.items()
        }
        owner = decoded.get("user_id") or None
        if user_id is not None and owner and owner != user_id:
            return None
        result = None
        if decoded.get("result"):
            try:
                result = json.loads(decoded["result"])
            except json.JSONDecodeError:
                result = decoded["result"]
        return Job(
            id=decoded["id"],
            job_type=decoded.get("type", ""),
            user_id=owner,
            status=decoded.get("status", "queued"),
            result=result,
            error=decoded.get("error") or None,
            created_at=float(decoded.get("created_at") or time.time()),
            updated_at=float(decoded.get("updated_at") or time.time()),
        )

    def reset_for_tests(self) -> None:
        for key in self._redis.scan_iter("careerai:job:*"):
            self._redis.delete(key)


def process_redis_job(job_id: str) -> None:
    """RQ entrypoint — runs inside the worker process."""
    from redis import Redis

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = Redis.from_url(redis_url)
    key = f"careerai:job:{job_id}"
    data = r.hgetall(key)
    if not data:
        return
    decoded = {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in data.items()
    }
    r.hset(key, mapping={"status": "running", "updated_at": str(time.time())})
    metrics.incr("jobs_running")
    try:
        payload = json.loads(decoded.get("payload") or "{}")
        result = execute_task(decoded.get("type", ""), payload)
        r.hset(
            key,
            mapping={
                "status": "done",
                "result": json.dumps(result),
                "updated_at": str(time.time()),
                "error": "",
            },
        )
        metrics.incr("jobs_done")
    except Exception as exc:
        logger.exception("redis job %s failed", job_id)
        r.hset(
            key,
            mapping={
                "status": "failed",
                "error": str(exc) or traceback.format_exc(limit=3),
                "updated_at": str(time.time()),
            },
        )
        metrics.incr("jobs_failed")


_manager = None
_manager_lock = threading.Lock()


def get_job_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            backend = _job_backend()
            if backend == "redis":
                url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                try:
                    _manager = RedisJobManager(url)
                    # ping
                    _manager._redis.ping()
                    logger.info("job backend=redis url=%s", url)
                except Exception:
                    logger.exception("Redis unavailable; falling back to memory jobs")
                    workers = int(os.getenv("ASYNC_JOB_WORKERS", "2"))
                    _manager = MemoryJobManager(max_workers=max(1, workers))
            else:
                workers = int(os.getenv("ASYNC_JOB_WORKERS", "2"))
                _manager = MemoryJobManager(max_workers=max(1, workers))
                logger.info("job backend=memory workers=%s", workers)
        return _manager


def reset_job_manager_for_tests():
    global _manager
    with _manager_lock:
        if _manager is not None:
            try:
                _manager.reset_for_tests()
            except Exception:
                pass
        os.environ["JOB_BACKEND"] = "memory"
        _manager = MemoryJobManager(max_workers=2)
        return _manager
