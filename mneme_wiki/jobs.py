"""In-memory job queue for long operations over MCP (TD-10).

One worker thread runs jobs in submission order, so integrations are serialised:
each one needs a clean vault and makes one commit, and the GPU runs one model
at a time anyway. Job state lives in memory and is lost when the server exits;
a finished job's effects are in the vault (and its git history).
"""

from __future__ import annotations

import queue
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

LOG_LINES_KEPT = 60
JobFn = Callable[[Callable[[str], None]], dict]  # fn(log) -> result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    subject: str
    status: str = "queued"  # queued | running | done | failed
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    log_lines: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.log_lines[-1] if self.log_lines else None,
            "log": list(self.log_lines[-20:]),
            "result": self.result,
            "error": self.error,
        }


class JobQueue:
    def __init__(self, on_log: Callable[[str], None] = lambda _m: None) -> None:
        self._jobs: dict[str, Job] = {}
        self._fns: dict[str, JobFn] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._on_log = on_log
        self._worker = threading.Thread(target=self._run, name="mneme-wiki-jobs", daemon=True)
        self._worker.start()

    def submit(self, kind: str, subject: str, fn: JobFn) -> Job:
        job = Job(uuid.uuid4().hex[:10], kind, subject)
        with self._lock:
            self._jobs[job.id] = job
            self._fns[job.id] = fn
        self._queue.put(job.id)
        return job

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None

    def list(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in j.snapshot().items() if k not in ("log", "result")}
                for j in self._jobs.values()
            ]

    def wait(self, timeout: float | None = None) -> bool:
        """Block until every submitted job finished (tests, shutdown)."""
        done = threading.Event()

        def check() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=check, daemon=True).start()
        return done.wait(timeout)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job, fn = self._jobs[job_id], self._fns.pop(job_id)
                job.status, job.started_at = "running", _now()

            def log(msg: str, job: Job = job) -> None:
                with self._lock:
                    job.log_lines.append(msg)
                    del job.log_lines[:-LOG_LINES_KEPT]
                self._on_log(f"[{job.id}] {msg}")

            try:
                result = fn(log)
                with self._lock:
                    job.result, job.status = result, "done"
            except Exception as exc:  # the job's failure is reported, the worker lives on
                with self._lock:
                    job.error, job.status = f"{type(exc).__name__}: {exc}", "failed"
                self._on_log(f"[{job.id}] failed: {traceback.format_exc(limit=3)}")
            finally:
                with self._lock:
                    job.finished_at = _now()
                self._queue.task_done()
