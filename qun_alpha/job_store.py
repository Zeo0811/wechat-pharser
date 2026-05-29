from __future__ import annotations
import json
import os
import threading


class JobStore:
    """任务记录落盘到 dir/<job_id>.json，线程安全。"""

    def __init__(self, dir: str = ".qun_jobs") -> None:
        self._dir = dir
        self._lock = threading.Lock()
        os.makedirs(dir, exist_ok=True)

    def _path(self, job_id: str) -> str:
        return os.path.join(self._dir, f"{job_id}.json")

    def _read(self, job_id: str) -> dict | None:
        p = self._path(job_id)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, rec: dict) -> None:
        with open(self._path(rec["job_id"]), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)

    def create(self, job_id: str, params: dict) -> None:
        with self._lock:
            self._write({"job_id": job_id, "params": params, "status": "running",
                         "done": [], "failed": [], "result": None})

    def load(self, job_id: str) -> dict | None:
        with self._lock:
            return self._read(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            out = []
            for fn in sorted(os.listdir(self._dir)):
                if fn.endswith(".json"):
                    with open(os.path.join(self._dir, fn), "r", encoding="utf-8") as f:
                        out.append(json.load(f))
            return out

    def mark_done(self, job_id: str, chunk_id: str) -> None:
        with self._lock:
            rec = self._read(job_id)
            if rec is None:
                return
            if chunk_id not in rec["done"]:
                rec["done"].append(chunk_id)
            self._write(rec)

    def mark_failed(self, job_id: str, chunk_id: str) -> None:
        with self._lock:
            rec = self._read(job_id)
            if rec is None:
                return
            if chunk_id not in rec["failed"]:
                rec["failed"].append(chunk_id)
            self._write(rec)

    def set_status(self, job_id: str, status: str, result: dict | None = None) -> None:
        with self._lock:
            rec = self._read(job_id)
            if rec is None:
                return
            rec["status"] = status
            if result is not None:
                rec["result"] = result
            self._write(rec)
