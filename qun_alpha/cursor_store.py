from __future__ import annotations
import json
import os
import threading


class CursorStore:
    """每群增量游标（group_id → 最近已处理 timestamp），落盘到单个 json。"""

    def __init__(self, path: str = ".qun_state/cursors.json") -> None:
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

    def get(self, key: str) -> int:
        with self._lock:
            return int(self._read().get(key, 0))

    def set(self, key: str, timestamp: int) -> None:
        with self._lock:
            data = self._read()
            if timestamp > int(data.get(key, 0)):
                data[key] = int(timestamp)
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
