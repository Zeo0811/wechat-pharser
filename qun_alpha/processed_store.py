from __future__ import annotations
import json
import os
import threading
from datetime import datetime
from typing import Optional


class ProcessedStore:
    """记录每个群被纳入成功分析的状态（runs 次数 + last 时间），文件落盘。"""

    def __init__(self, path: str = ".qun_state/processed.json") -> None:
        self._path = path
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    def _read(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def mark(self, group_ids: list, when: Optional[str] = None) -> None:
        if not group_ids:
            return
        when = when or datetime.now().isoformat(timespec="seconds")
        with self._lock:
            data = self._read()
            for g in group_ids:
                e = data.get(g, {"runs": 0, "last": None})
                e["runs"] = int(e.get("runs", 0)) + 1
                e["last"] = when
                data[g] = e
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, group_id: str) -> Optional[dict]:
        with self._lock:
            return self._read().get(group_id)

    def all(self) -> dict:
        with self._lock:
            return self._read()
