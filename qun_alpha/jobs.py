from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    job_id: str
    status: str = "running"          # running | done | error
    events: list = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    _thread: Optional[threading.Thread] = None


class JobManager:
    """跑任意 target(emit)->dict，后台线程执行，进度事件缓冲在 Job 上。"""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def _new_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"job{self._counter}"

    def start(self, target: Callable[[Callable[[Any], None]], dict]) -> str:
        job_id = self._new_id()
        job = Job(job_id=job_id)
        self._jobs[job_id] = job

        def emit(ev: Any) -> None:
            job.events.append(ev)

        def run() -> None:
            try:
                job.result = target(emit)
                job.status = "done"
            except Exception as e:           # noqa: BLE001 —— 任务失败要落到 job 上
                job.error = str(e)
                job.status = "error"

        t = threading.Thread(target=run, daemon=True)
        job._thread = t
        t.start()
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def join(self, job_id: str, timeout: float = 5.0) -> None:
        job = self._jobs.get(job_id)
        if job and job._thread is not None:
            job._thread.join(timeout)
