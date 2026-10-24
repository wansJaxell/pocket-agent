"""The background job queue: one agent, one worker, jobs run one after another.

Chat messages from the panel and Telegram become jobs, so the panel and the Telegram poller stay
responsive while the agent thinks (they must be: approvals and the stop button arrive meanwhile).
"""

import itertools
import queue
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any, Callable


class Job:
    def __init__(self, job_id: str, label: str, func: Callable[[], Any], source: str):
        self.id, self.label, self.func, self.source = job_id, label, func, source
        self.status = "queued"        # queued -> running -> done / failed / cancelled
        self.result: Any = None
        self.error = ""
        self.created = datetime.now().isoformat(timespec="seconds")
        self.done = threading.Event()

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "source": self.source, "status": self.status,
                "result": self.result, "error": self.error, "created": self.created}


class JobQueue:
    def __init__(self, keep: int = 50):
        self.jobs: OrderedDict[str, Job] = OrderedDict()
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._keep = keep
        self._worker: threading.Thread | None = None
        self.current: Job | None = None

    def submit(self, label: str, func: Callable[[], Any], source: str = "panel") -> Job:
        with self._lock:
            job = Job(str(next(self._ids)), label, func, source)
            self.jobs[job.id] = job
            while len(self.jobs) > self._keep:                    # forget old finished jobs
                oldest = next(iter(self.jobs.values()))
                if not oldest.done.is_set():
                    break
                self.jobs.popitem(last=False)
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="pocketagent-jobs", daemon=True)
                self._worker.start()
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(str(job_id))

    def recent(self, limit: int = 20) -> list[dict]:
        return [j.as_dict() for j in reversed(list(self.jobs.values()))][:limit]

    def cancel_waiting(self) -> int:
        """Cancel every job that has not started yet; returns how many."""
        count = 0
        with self._lock:
            for job in self.jobs.values():
                if job.status == "queued":
                    job.status = "cancelled"
                    job.done.set()
                    count += 1
        return count

    def cancel_running(self) -> bool:
        """Mark the running job as cancelled at once (the stop button ends its work separately)."""
        with self._lock:
            job = self.current
            if job is None or job.status != "running":
                return False
            job.status = "cancelled"
            job.done.set()
            return True

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            with self._lock:
                if job.status != "queued":
                    continue
                job.status, self.current = "running", job
            try:
                result = job.func()
                if job.status == "running":
                    job.status, job.result = "done", result
            except Exception as error:   # a failing job must not stop the queue
                if job.status == "running":
                    job.status, job.error = "failed", f"{type(error).__name__}: {error}"
            finally:
                self.current = None
                job.done.set()
