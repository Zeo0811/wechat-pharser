# 群聊投资机会分析 — Job 引擎 (Plan 2b-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把阻塞式的 run_pipeline 升级为带进度事件的 `orchestrator.run_job`，加上群列表查询和一个内存 JobManager（后台线程跑任务、缓冲进度事件），为 2b-2 的 Web 操作台备好后端引擎。

**Architecture:** `orchestrator.run_job` 复用已合并的纯函数管线，每个阶段 `emit(ProgressEvent)`；`cli.run_pipeline` 重构为 run_job 的薄封装（emit 为 no-op），保持既有 cli 行为与测试不变（DRY）。`JobManager` 用内存 dict + 后台线程跑任意 `target(emit)->dict`，缓冲事件供后续 SSE 读取。零新依赖。

**Tech Stack:** Python 3.10+（dataclasses + threading，stdlib），pydantic v2，pytest。沿用 `~/qun-alpha/.venv`，测试 `.venv/bin/pytest`。

---

## File Structure

```
qun_alpha/
  orchestrator.py   # 新：ProgressEvent + run_job(带 emit 的全管线)
  jobs.py           # 新：Job + JobManager(后台线程跑 target、缓冲事件)
  chat_reader.py    # 改：增 list_groups(export_path)
  cli.py            # 改：run_pipeline 重构为 orchestrator.run_job 的薄封装
tests/
  test_orchestrator.py   # 新
  test_jobs.py           # 新
  test_chat_reader.py    # 改：增 list_groups 测试
  （test_cli_smoke.py 不改，应保持通过）
```

run_job 的返回 dict 与现有 run_pipeline 完全一致（chunks/raw_entities/companies/people/links/company_payloads/people_payloads/link_payloads），额外通过 emit 推进度。

---

## Task 1: orchestrator.run_job（进度事件）+ cli 重构

**Files:**
- Create: `qun_alpha/orchestrator.py`
- Test: `tests/test_orchestrator.py`
- Modify: `qun_alpha/cli.py`

- [ ] **Step 1: 写失败测试 `tests/test_orchestrator.py`**

```python
import json
from qun_alpha.orchestrator import run_job, ProgressEvent


def _fake_runner(prompt):
    import re
    m = re.search(r"msg_id=(\w+)", prompt)
    mid = m.group(1) if m else "m1"
    return json.dumps([
        {"kind": "company", "name": "IrisGo", "quote": "拿了$2.8M种子轮",
         "commentary": "under-the-radar AI seed",
         "source": {"group_name": "AI投资群", "sender": "老王",
                    "timestamp": 1716700000, "msg_id": mid},
         "financials": "$2.8M 种子轮", "investors": ["AI Fund"], "confidence": 0.8},
    ])


def _run(tmp_path):
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
    )
    return events, result


def test_run_job_returns_same_shape_as_pipeline(tmp_path):
    events, result = _run(tmp_path)
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["company_payloads"][0]["parent"]["database_id"] == "cdb"
    assert set(result.keys()) >= {
        "chunks", "raw_entities", "companies", "people", "links",
        "company_payloads", "people_payloads", "link_payloads"}


def test_run_job_emits_progress_stages(tmp_path):
    events, _ = _run(tmp_path)
    assert all(isinstance(e, ProgressEvent) for e in events)
    stages = [e.stage for e in events]
    # 阶段顺序：read → extract(逐块) → aggregate → write → done
    assert stages[0] == "read"
    assert stages[-1] == "done"
    assert "extract" in stages
    assert "aggregate" in stages
    assert "write" in stages
    # extract 每块一次（2 块）
    assert stages.count("extract") == 2
    # 末尾 done 事件 current==total
    assert events[-1].current == events[-1].total
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_orchestrator.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.orchestrator'`

- [ ] **Step 3: 实现 `qun_alpha/orchestrator.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Optional
from qun_alpha import chat_reader, extractor, aggregator, notion_writer


@dataclass
class ProgressEvent:
    stage: str          # read | extract | aggregate | write | done
    current: int
    total: int
    message: str


Emit = Callable[["ProgressEvent"], None]


def _noop(_ev: "ProgressEvent") -> None:
    pass


def run_job(*, export_path: str, group_ids: list[str], start: int, end: int,
            max_messages: int, prompt_version: str,
            runner: Callable[[str], str], cache_dir: Optional[str],
            notion_client: Any,
            companies_db_id: str, people_db_id: str, links_db_id: str,
            dry_run: bool, emit: Emit = _noop) -> dict:
    emit(ProgressEvent("read", 0, 1, "读取并切块"))
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)
    total = len(chunks)
    emit(ProgressEvent("read", 1, 1, f"共 {total} 块"))

    raw: list = []
    for i, ch in enumerate(chunks):
        raw.extend(extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir))
        emit(ProgressEvent("extract", i + 1, total, f"抽取 {i + 1}/{total} 块"))

    emit(ProgressEvent("aggregate", 0, 1, "聚合打分"))
    companies, people, links = aggregator.aggregate(raw)
    emit(ProgressEvent("aggregate", 1, 1,
                       f"{len(companies)}公司/{len(people)}人/{len(links)}链接"))

    emit(ProgressEvent("write", 0, 1, "写 Notion"))
    company_payloads = notion_writer.write_companies(
        companies, client=notion_client, database_id=companies_db_id, dry_run=dry_run)
    people_payloads = notion_writer.write_people(
        people, client=notion_client, database_id=people_db_id, dry_run=dry_run)
    link_payloads = notion_writer.write_links(
        links, client=notion_client, database_id=links_db_id, dry_run=dry_run)
    emit(ProgressEvent("write", 1, 1, "写入完成"))

    result = {
        "chunks": total,
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "company_payloads": company_payloads,
        "people_payloads": people_payloads,
        "link_payloads": link_payloads,
    }
    emit(ProgressEvent("done", 1, 1, "完成"))
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_orchestrator.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 重构 `qun_alpha/cli.py` 的 run_pipeline 为薄封装**

把 `run_pipeline` 函数整体替换为下面（其余 cli.py 内容不动），并确保文件顶部 import 增加 orchestrator：

把 import 行
```python
from qun_alpha import chat_reader, extractor, aggregator, notion_writer
```
改为
```python
from qun_alpha import chat_reader, extractor, aggregator, notion_writer, orchestrator
```

把整个 `run_pipeline(...)` 函数体替换为：
```python
def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 notion_client: Any,
                 companies_db_id: str, people_db_id: str, links_db_id: str,
                 dry_run: bool) -> dict:
    return orchestrator.run_job(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=max_messages, prompt_version=prompt_version,
        runner=runner, cache_dir=cache_dir, notion_client=notion_client,
        companies_db_id=companies_db_id, people_db_id=people_db_id,
        links_db_id=links_db_id, dry_run=dry_run,
    )
```

- [ ] **Step 6: 跑 cli 冒烟 + 全套确认无回归**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（35 + 新增 orchestrator 2 = 37 passed）

- [ ] **Step 7: Commit**

```bash
git add qun_alpha/orchestrator.py qun_alpha/cli.py tests/test_orchestrator.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: orchestrator.run_job 带进度事件 + cli.run_pipeline 重构为薄封装"
```

---

## Task 2: chat_reader.list_groups

**说明**：Web 操作台选群需要"群列表 + 各群消息数"。

**Files:**
- Modify: `qun_alpha/chat_reader.py`
- Test: `tests/test_chat_reader.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_chat_reader.py` 末尾**

```python
def test_list_groups_counts_and_sorts():
    from qun_alpha.chat_reader import list_groups
    groups = list_groups(FIX)
    # 两个群：g1(4 条) / g2(1 条)，按消息数降序
    assert [g["group_id"] for g in groups] == ["g1", "g2"]
    g1 = groups[0]
    assert g1["group_name"] == "AI投资群"
    assert g1["count"] == 4
    assert groups[1]["count"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_chat_reader.py::test_list_groups_counts_and_sorts -q`
Expected: FAIL，`ImportError: cannot import name 'list_groups'`

- [ ] **Step 3: 在 `qun_alpha/chat_reader.py` 末尾追加：**

```python
def list_groups(export_path: str) -> list[dict]:
    """返回 [{group_id, group_name, count}]，按消息数降序。"""
    messages = load_export(export_path)
    agg: dict[str, dict] = {}
    for m in messages:
        g = agg.setdefault(m.group_id, {
            "group_id": m.group_id, "group_name": m.group_name, "count": 0})
        g["group_name"] = m.group_name      # 以最后出现的群名为准
        g["count"] += 1
    return sorted(agg.values(), key=lambda g: g["count"], reverse=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_chat_reader.py -q`
Expected: PASS（7 passed —— 原 6 + 新 1）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/chat_reader.py tests/test_chat_reader.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: chat_reader.list_groups 群列表+消息数"
```

---

## Task 3: JobManager（内存 + 后台线程）

**说明**：跑任意 `target(emit)->dict`，后台线程执行，进度事件缓冲在 Job 上，供 2b-2 的 SSE 读取。

**Files:**
- Create: `qun_alpha/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: 写失败测试 `tests/test_jobs.py`**

```python
import time
from qun_alpha.jobs import JobManager


def test_job_runs_and_collects_events_and_result():
    mgr = JobManager()

    def target(emit):
        emit("e1")
        emit("e2")
        return {"ok": True}

    job_id = mgr.start(target)
    mgr.join(job_id)
    job = mgr.get(job_id)
    assert job.status == "done"
    assert job.events == ["e1", "e2"]
    assert job.result == {"ok": True}
    assert job.error is None


def test_job_records_error():
    mgr = JobManager()

    def boom(emit):
        emit("started")
        raise ValueError("炸了")

    job_id = mgr.start(boom)
    mgr.join(job_id)
    job = mgr.get(job_id)
    assert job.status == "error"
    assert "炸了" in job.error
    assert job.events == ["started"]


def test_job_ids_unique():
    mgr = JobManager()
    a = mgr.start(lambda emit: {})
    b = mgr.start(lambda emit: {})
    assert a != b


def test_get_unknown_returns_none():
    assert JobManager().get("nope") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.jobs'`

- [ ] **Step 3: 实现 `qun_alpha/jobs.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 跑全套**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（约 42 passed：37 + chat_reader 1 + jobs 4）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/jobs.py tests/test_jobs.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: JobManager 内存注册表 + 后台线程跑任务缓冲进度"
```

---

## 完成标准（Plan 2b-1）

- [ ] `pytest -q` 全绿（约 42 passed）
- [ ] `orchestrator.run_job` 返回与 run_pipeline 一致的 dict，并 emit 五阶段事件（read→extract×N→aggregate→write→done）
- [ ] `cli.run_pipeline` 是 run_job 的薄封装，既有 cli 冒烟测试仍通过（无重复管线逻辑）
- [ ] `chat_reader.list_groups` 返回按消息数降序的群列表
- [ ] `JobManager` 后台线程跑 target，缓冲事件、记录 result/error，job_id 唯一

## 后续（Plan 2b-2）

- FastAPI app：`GET /api/groups`、`POST /api/jobs`、`GET /api/jobs/{id}`、`GET /api/jobs/{id}/stream`(SSE)、`GET /`(前端)
- 前端 index.html（原生 JS + EventSource）：选群/时间范围 → 进度条 → 结果摘要
- `qun-alpha serve` 命令（uvicorn + 自动开浏览器，带 --no-browser）
- 依赖：fastapi + uvicorn（运行时）、httpx（dev，TestClient）
