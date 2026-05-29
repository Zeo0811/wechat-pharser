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

    def __init__(self, job_store: Optional[Any] = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._store = job_store

    def _new_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"job{self._counter}"

    def start(self, target: Callable[[Callable[[Any], None]], dict],
              params: Optional[dict] = None) -> str:
        job_id = self._new_id()
        job = Job(job_id=job_id)
        self._jobs[job_id] = job
        if self._store is not None:
            self._store.create(job_id, params or {})

        def emit(ev: Any) -> None:
            job.events.append(ev)

        def run() -> None:
            try:
                job.result = target(emit)
                job.status = "done"
                if self._store is not None:
                    self._store.set_status(job_id, "done", result=job.result)
            except Exception as e:           # noqa: BLE001
                job.error = str(e)
                job.status = "error"
                if self._store is not None:
                    self._store.set_status(job_id, "error")

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

    def resume(self, job_id: str,
               build_target: Callable[[dict], Callable[[Callable[[Any], None]], dict]]) -> str:
        """用持久化的 params 重跑（缓存自动跳过已完成块）。需要 job_store。"""
        if self._store is None:
            raise RuntimeError("resume 需要 JobManager 配置 job_store")
        rec = self._store.load(job_id)
        if rec is None:
            raise KeyError(f"未知任务：{job_id}")
        params = rec.get("params", {})
        self._store.set_status(job_id, "running")
        target = build_target(params)
        job = self._jobs.get(job_id) or Job(job_id=job_id)
        job.status = "running"
        job.events = []
        self._jobs[job_id] = job

        def emit(ev: Any) -> None:
            job.events.append(ev)

        def run() -> None:
            try:
                job.result = target(emit)
                job.status = "done"
                self._store.set_status(job_id, "done", result=job.result)
            except Exception as e:           # noqa: BLE001
                job.error = str(e)
                job.status = "error"
                self._store.set_status(job_id, "error")

        t = threading.Thread(target=run, daemon=True)
        job._thread = t
        t.start()
        return job_id
