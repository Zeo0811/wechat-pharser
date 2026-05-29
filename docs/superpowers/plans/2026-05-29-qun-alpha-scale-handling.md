# Spec A 大任务扛量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 让大任务可重复、可续、可增量、可预估：任务状态落盘 + resume + 每群增量游标 + 跑前规模/成本预估 + 有界并发抽取。

**Architecture:** 复用 extractor 已有的块级磁盘缓存（重跑自动跳过已完成块）。新增 `job_store`（任务进度落盘）、`cursor_store`（每群增量游标）、`estimate`（跑前预估）；改 `orchestrator.run_job` 支持有界并发 + 进度落盘 + 增量过滤 + 成功后推进游标；`JobManager` 加 resume。所有新组件 client/store 注入，纯 I/O 逻辑用 tmp_path 测，抽取用 fake runner 测，不碰真模型。

**Tech Stack:** Python 3.10+（json/os/threading/concurrent.futures，stdlib），pydantic v2，pytest。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/
  job_store.py      # 新：JobStore 任务记录落盘 .qun_jobs/<id>.json
  cursor_store.py   # 新：CursorStore 每群游标 .qun_state/cursors.json
  estimate.py       # 新：estimate_run() 跑前预估
  orchestrator.py   # 改：run_job 加 concurrency/job_store/incremental/cursor_store
  jobs.py           # 改：JobManager 接 job_store + resume
tests/
  test_job_store.py / test_cursor_store.py / test_estimate.py（新）
  test_orchestrator.py（改：加并发/落盘/增量用例）
  test_jobs.py（改：加 resume/持久化用例）
```

现有 `run_job` 签名（Plan 2b-1）：
```python
run_job(*, export_path, group_ids, start, end, max_messages, prompt_version,
        runner, cache_dir, notion_client, companies_db_id, people_db_id, links_db_id,
        dry_run, emit=_noop) -> dict
```
新增参数都带默认值，保持 `cli.run_pipeline` 与现有测试不变。

---

## Task 1: job_store（任务进度落盘）

**Files:** Create `qun_alpha/job_store.py`; Test `tests/test_job_store.py`

- [ ] **Step 1: 写失败测试 `tests/test_job_store.py`**

```python
from qun_alpha.job_store import JobStore


def test_create_load_list(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("job1", {"export_path": "x.json", "group_ids": ["g1"]})
    rec = s.load("job1")
    assert rec["status"] == "running"
    assert rec["params"]["group_ids"] == ["g1"]
    assert rec["done"] == [] and rec["failed"] == []
    assert [r["job_id"] for r in s.list()] == ["job1"]


def test_mark_done_failed_dedup(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("j", {})
    s.mark_done("j", "c1")
    s.mark_done("j", "c1")          # 幂等
    s.mark_done("j", "c2")
    s.mark_failed("j", "c3")
    rec = s.load("j")
    assert rec["done"] == ["c1", "c2"]
    assert rec["failed"] == ["c3"]


def test_set_status_and_result(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("j", {})
    s.set_status("j", "done", result={"companies": 3})
    rec = s.load("j")
    assert rec["status"] == "done"
    assert rec["result"]["companies"] == 3


def test_load_missing_returns_none(tmp_path):
    assert JobStore(dir=str(tmp_path)).load("nope") is None
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_job_store.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/job_store.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_job_store.py -q` → Expected: 4 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/job_store.py tests/test_job_store.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: job_store 任务进度落盘"
```

---

## Task 2: cursor_store（每群增量游标）

**Files:** Create `qun_alpha/cursor_store.py`; Test `tests/test_cursor_store.py`

- [ ] **Step 1: 写失败测试 `tests/test_cursor_store.py`**

```python
from qun_alpha.cursor_store import CursorStore


def test_default_zero(tmp_path):
    s = CursorStore(path=str(tmp_path / "cursors.json"))
    assert s.get("g1") == 0


def test_set_get_persist(tmp_path):
    p = str(tmp_path / "cursors.json")
    s = CursorStore(path=p)
    s.set("g1", 1716700000)
    assert s.get("g1") == 1716700000
    # 新实例从磁盘读到
    assert CursorStore(path=p).get("g1") == 1716700000


def test_set_only_advances(tmp_path):
    s = CursorStore(path=str(tmp_path / "cursors.json"))
    s.set("g1", 100)
    s.set("g1", 50)            # 不回退
    assert s.get("g1") == 100
    s.set("g1", 200)
    assert s.get("g1") == 200
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_cursor_store.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/cursor_store.py`**

```python
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
            if timestamp > int(data.get(key, 0)):     # 只前进，不回退
                data[key] = int(timestamp)
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_cursor_store.py -q` → Expected: 3 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/cursor_store.py tests/test_cursor_store.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: cursor_store 每群增量游标"
```

---

## Task 3: estimate（跑前预估）

**Files:** Create `qun_alpha/estimate.py`; Test `tests/test_estimate.py`

- [ ] **Step 1: 写失败测试 `tests/test_estimate.py`**

```python
import os
import json
from qun_alpha.estimate import estimate_run

FIX = "tests/fixtures/export_sample.json"


def test_estimate_counts_chunks(tmp_path):
    est = estimate_run(export_path=FIX, group_ids=["g1"], start=0, end=2_000_000_000,
                       max_messages=1, prompt_version="v1", cache_dir=str(tmp_path))
    # g1 去噪后剩 m1/m4 两条 → max_messages=1 → 2 块
    assert est["chunks"] == 2
    assert est["cached"] == 0
    assert est["to_run"] == 2
    assert est["est_tokens"] > 0
    assert est["est_cost_usd"] >= 0
    assert est["est_minutes"] >= 0


def test_estimate_counts_cache_hits(tmp_path):
    # 预先放一个缓存文件命中其中一块
    from qun_alpha import chat_reader
    msgs = chat_reader.load_export(FIX)
    g1 = chat_reader.filter_messages(msgs, group_ids=["g1"], start=0,
                                     end=2_000_000_000, drop_noise=True)
    chunks = chat_reader.chunk_messages(g1, max_messages=1, prompt_version="v1")
    os.makedirs(tmp_path, exist_ok=True)
    with open(os.path.join(str(tmp_path), f"{chunks[0].chunk_id}.json"), "w") as f:
        json.dump([], f)
    est = estimate_run(export_path=FIX, group_ids=["g1"], start=0, end=2_000_000_000,
                       max_messages=1, prompt_version="v1", cache_dir=str(tmp_path))
    assert est["chunks"] == 2
    assert est["cached"] == 1
    assert est["to_run"] == 1
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_estimate.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/estimate.py`**

```python
from __future__ import annotations
import os
from qun_alpha import chat_reader

# 粗估常量（可按需调）
AVG_TOKENS_PER_CHUNK = 7500       # 输入+输出粗估
USD_PER_CHUNK = 0.02              # 粗估单价（claude -p 走订阅时仅供参考）
SECONDS_PER_CHUNK = 8            # 粗估单块耗时


def estimate_run(*, export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str, cache_dir: str) -> dict:
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)

    cached = 0
    for ch in chunks:
        if cache_dir and os.path.exists(os.path.join(cache_dir, f"{ch.chunk_id}.json")):
            cached += 1
    to_run = len(chunks) - cached
    return {
        "chunks": len(chunks),
        "cached": cached,
        "to_run": to_run,
        "est_tokens": to_run * AVG_TOKENS_PER_CHUNK,
        "est_cost_usd": round(to_run * USD_PER_CHUNK, 2),
        "est_minutes": round(to_run * SECONDS_PER_CHUNK / 60, 1),
    }
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_estimate.py -q` → Expected: 2 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/estimate.py tests/test_estimate.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: estimate 跑前规模/成本预估"
```

---

## Task 4: orchestrator 有界并发 + 进度落盘

**说明**：把顺序抽取换成有界线程池（默认并发 3），并在每块完成/失败时写 job_store。新增参数都有默认值，保持现有测试与 cli 不变。

**Files:** Modify `qun_alpha/orchestrator.py`; Test `tests/test_orchestrator.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_orchestrator.py` 末尾**

```python
from qun_alpha.job_store import JobStore


def test_run_job_records_progress_to_store(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    store.create("jx", {})
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
        concurrency=3, job_store=store, job_id="jx",
    )
    assert result["chunks"] == 2
    rec = store.load("jx")
    assert len(rec["done"]) == 2          # 两块都落盘
    assert rec["failed"] == []
    # 抽取事件仍每块一次
    assert [e.stage for e in events].count("extract") == 2
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_orchestrator.py::test_run_job_records_progress_to_store -q`
Expected: FAIL（run_job 无 concurrency/job_store/job_id 参数 → TypeError）

- [ ] **Step 3: 修改 `qun_alpha/orchestrator.py`**

在文件顶部 import 增加：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
```
（若已有 `from typing import Any, Callable, Optional` 则不重复加 Optional）

把 `run_job` 的签名改为（追加 4 个带默认值的参数）：
```python
def run_job(*, export_path: str, group_ids: list[str], start: int, end: int,
            max_messages: int, prompt_version: str,
            runner: Callable[[str], str], cache_dir: Optional[str],
            notion_client: Any,
            companies_db_id: str, people_db_id: str, links_db_id: str,
            dry_run: bool, emit: Emit = _noop,
            concurrency: int = 3, job_store: Any = None,
            job_id: Optional[str] = None) -> dict:
```

把原来顺序抽取这段：
```python
    raw: list = []
    for i, ch in enumerate(chunks):
        raw.extend(extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir))
        emit(ProgressEvent("extract", i + 1, total, f"抽取 {i + 1}/{total} 块"))
```
替换为有界并发版：
```python
    raw: list = []
    done = 0

    def _extract(ch):
        return ch, extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_extract, ch) for ch in chunks]
        for fut in as_completed(futures):
            done += 1
            try:
                ch, entities = fut.result()
                raw.extend(entities)
                if job_store is not None and job_id is not None:
                    job_store.mark_done(job_id, ch.chunk_id)
            except Exception:
                if job_store is not None and job_id is not None:
                    # 失败块无法拿到 chunk_id（future 抛异常），记一个占位
                    job_store.mark_failed(job_id, f"unknown_{done}")
            emit(ProgressEvent("extract", done, total, f"抽取 {done}/{total} 块"))
```

其余（read/aggregate/write/done 与返回 dict）保持不变。

- [ ] **Step 4: 运行确认通过 + 全套无回归**
Run: `.venv/bin/pytest tests/test_orchestrator.py -q` → Expected: 3 passed
Run: `.venv/bin/pytest -q` → Expected: 全绿（既有用例不受影响）

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/orchestrator.py tests/test_orchestrator.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: orchestrator 有界并发抽取 + 进度落盘"
```

---

## Task 5: orchestrator 增量游标

**说明**：新增 `incremental` + `cursor_store`。增量时按每群游标过滤掉旧消息；整群成功后把游标推进到该群本次最大 timestamp。

**Files:** Modify `qun_alpha/orchestrator.py`; Test `tests/test_orchestrator.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_orchestrator.py` 末尾**

```python
from qun_alpha.cursor_store import CursorStore


def test_incremental_skips_old_and_advances_cursor(tmp_path):
    cur = CursorStore(path=str(tmp_path / "cursors.json"))
    cur.set("g1", 1716700000)        # m1(=1716700000) 及更早应被跳过；m4(1716786400) 保留
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
        incremental=True, cursor_store=cur,
    )
    # 只剩 m4 一块（m1 被游标过滤；m2/m3 是噪声）
    assert result["chunks"] == 1
    # 整群成功后游标推进到 g1 本次最大 ts = 1716786400
    assert cur.get("g1") == 1716786400
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_orchestrator.py::test_incremental_skips_old_and_advances_cursor -q`
Expected: FAIL（run_job 无 incremental/cursor_store 参数 → TypeError）

- [ ] **Step 3: 修改 `qun_alpha/orchestrator.py`**

在 run_job 签名再追加两个带默认值的参数（放在 job_id 之后）：
```python
            job_id: Optional[str] = None,
            incremental: bool = False, cursor_store: Any = None) -> dict:
```

在 `filtered = chat_reader.filter_messages(...)` 之后、`chunks = ...` 之前，插入增量过滤：
```python
    if incremental and cursor_store is not None:
        filtered = [m for m in filtered
                    if m.timestamp > cursor_store.get(m.group_id)]
```

在函数末尾、`emit(ProgressEvent("done", ...))` 之前，插入游标推进（按本次处理到的每群最大 timestamp）：
```python
    if incremental and cursor_store is not None:
        latest: dict[str, int] = {}
        for ch in chunks:
            latest[ch.group_id] = max(latest.get(ch.group_id, 0), ch.time_end)
        for gid, ts in latest.items():
            cursor_store.set(gid, ts)
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_orchestrator.py -q` → Expected: 4 passed
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/orchestrator.py tests/test_orchestrator.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: orchestrator 增量游标过滤+推进"
```

---

## Task 6: JobManager resume + 持久化包装

**说明**：JobManager 接受可选 job_store，start 时落盘 params/状态，新增 `resume(job_id, build_target)` 用持久化的 params 重跑（缓存自动跳过已完成块）。

**Files:** Modify `qun_alpha/jobs.py`; Test `tests/test_jobs.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_jobs.py` 末尾**

```python
from qun_alpha.job_store import JobStore


def test_start_persists_params_and_resume(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    mgr = JobManager(job_store=store)
    runs = []

    def build_target(params):
        def target(emit):
            runs.append(params["n"])
            return {"n": params["n"]}
        return target

    job_id = mgr.start(build_target({"n": 1}), params={"n": 1})
    mgr.join(job_id)
    # 落盘了 params 与 done 状态
    rec = store.load(job_id)
    assert rec["params"]["n"] == 1
    assert rec["status"] == "done"

    # resume：用持久化 params 重跑同一 build_target
    mgr.resume(job_id, build_target)
    mgr.join(job_id)
    assert runs == [1, 1]          # 跑了两次（resume 重跑）


def test_start_without_store_still_works():
    mgr = JobManager()
    jid = mgr.start(lambda emit: {"ok": True})
    mgr.join(jid)
    assert mgr.get(jid).status == "done"
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: FAIL（JobManager 不接受 job_store / 无 resume / start 无 params）

- [ ] **Step 3: 修改 `qun_alpha/jobs.py`**

把 `JobManager.__init__` 改为接受可选 job_store：
```python
    def __init__(self, job_store: "object | None" = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._store = job_store
```

把 `start` 改为接受可选 params 并落盘：
```python
    def start(self, target: "Callable[[Callable[[Any], None]], dict]",
              params: "dict | None" = None) -> str:
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
```

新增 `resume`（放在 join 之后）：
```python
    def resume(self, job_id: str,
               build_target: "Callable[[dict], Callable[[Callable[[Any], None]], dict]]"):
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
```

注意：顶部需有 `from typing import Any, Callable, Optional`（Plan 2b-1 已有则不动）。

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_jobs.py -q` → Expected: 通过（原 4 + 新 2 = 6）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/jobs.py tests/test_jobs.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: JobManager 持久化 + resume"
```

---

## 完成标准（Spec A）
- [ ] `pytest -q` 全绿
- [ ] job_store/cursor_store 落盘存取正确、线程安全
- [ ] estimate 返回块数/缓存命中/to_run/token/$/分钟，缓存命中减少 to_run
- [ ] run_job 有界并发（默认 3）+ 完成块落盘 + 增量过滤 + 游标推进
- [ ] JobManager 持久化 params 且 resume 能用原 params 重跑
- [ ] 既有 cli/web 测试不受影响（新参数全有默认值）

## 后续（Spec B 接线 / 不在本计划）
- web/cli 暴露 estimate 端点、resume/增量入口、并发配置（Spec B UI 接线时一起做）。
- 真实大数据端到端验收。
