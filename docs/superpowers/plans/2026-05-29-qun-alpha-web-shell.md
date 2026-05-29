# 群聊投资机会分析 — Web 操作台壳 (Plan 2b-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 Plan 2b-1 的 Job 引擎之上套一层本地 Web 操作台：FastAPI 端点（群列表 / 起任务 / 查状态 / SSE 进度）+ 原生 JS 前端（选群→进度条→结果）+ `qun-alpha serve` 一键起服务并开浏览器。

**Architecture:** `web.create_app()` 用依赖注入（manager、target_factory、groups_provider）便于 TestClient 测试，无真模型/真 Notion。SSE 进度抽成可独立测试的纯生成器 `iter_sse(manager, job_id)`，路由只是薄包装。前端是单个静态 `index.html`（原生 fetch + EventSource，无构建步骤）。`serve` 命令薄，主体逻辑都在 `create_app`。

**Tech Stack:** Python 3.10+，FastAPI + uvicorn（运行时），httpx（dev，TestClient），pydantic v2，pytest。沿用 `~/qun-alpha/.venv`。

---

## File Structure

```
qun_alpha/
  web.py                  # 新：create_app + iter_sse + _default_target_factory + _ev/_sse
  static/index.html       # 新：前端单页
  cli.py                  # 改：增 serve 命令
pyproject.toml            # 改：加 fastapi/uvicorn 运行时 + httpx dev
tests/
  test_web.py             # 新：TestClient 测端点 + iter_sse 直测
```

---

## Task 1: 加依赖

**Files:** Modify `pyproject.toml`

- [ ] **Step 1: 改 `pyproject.toml`**

把 `dependencies` 数组改为（追加 fastapi、uvicorn）：
```toml
dependencies = [
    "pydantic>=2,<3",
    "typer>=0.12,<1",
    "notion-client>=2.2,<3",
    "fastapi>=0.110,<1",
    "uvicorn>=0.27,<1",
]
```

把 `[project.optional-dependencies]` 的 dev 改为（追加 httpx）：
```toml
[project.optional-dependencies]
dev = ["pytest>=8,<9", "httpx>=0.27,<1"]
```

- [ ] **Step 2: 安装**

Run: `cd ~/qun-alpha && .venv/bin/pip install -e ".[dev]"`
Expected: 安装成功（fastapi / uvicorn / starlette / httpx 等到位）

- [ ] **Step 3: 确认现有测试仍绿**

Run: `.venv/bin/pytest -q`
Expected: 42 passed

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "chore: 加 fastapi/uvicorn 运行时 + httpx dev 依赖"
```

---

## Task 2: web.create_app —— 群列表 / 起任务 / 查状态

**Files:**
- Create: `qun_alpha/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: 写失败测试 `tests/test_web.py`**

```python
from fastapi.testclient import TestClient
from qun_alpha.jobs import JobManager
from qun_alpha.web import create_app


def _client(manager):
    # 注入：群列表返回假数据；target 只 emit 两个事件并返回 summary
    def groups_provider(export_path):
        return [{"group_id": "g1", "group_name": "AI投资群", "count": 4}]

    def target_factory(params):
        def target(emit):
            emit({"stage": "read", "current": 1, "total": 1, "message": "ok"})
            emit({"stage": "done", "current": 1, "total": 1, "message": "完成"})
            return {"companies": 1, "people": 0, "links": 0,
                    "group_ids": params["group_ids"]}
        return target

    app = create_app(manager=manager, target_factory=target_factory,
                     groups_provider=groups_provider)
    return TestClient(app)


def test_groups_endpoint():
    client = _client(JobManager())
    r = client.get("/api/groups", params={"export_path": "x.json"})
    assert r.status_code == 200
    assert r.json()[0]["group_id"] == "g1"


def test_start_job_and_poll_status():
    mgr = JobManager()
    client = _client(mgr)
    r = client.post("/api/jobs", json={"export_path": "x.json",
                                       "group_ids": ["g1"], "dry_run": True})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    mgr.join(job_id)
    s = client.get(f"/api/jobs/{job_id}")
    assert s.status_code == 200
    body = s.json()
    assert body["status"] == "done"
    assert body["result"]["companies"] == 1
    assert body["result"]["group_ids"] == ["g1"]
    assert len(body["events"]) == 2


def test_unknown_job_404():
    client = _client(JobManager())
    assert client.get("/api/jobs/nope").status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.web'`

- [ ] **Step 3: 实现 `qun_alpha/web.py`（本任务只做端点，SSE 在 Task 3 追加）**

```python
from __future__ import annotations
import dataclasses
from typing import Any, Callable, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from qun_alpha import chat_reader
from qun_alpha.jobs import JobManager

TargetFactory = Callable[[dict], Callable[[Callable[[Any], None]], dict]]
GroupsProvider = Callable[[str], list]


def _ev(e: Any) -> dict:
    """ProgressEvent(dataclass) → dict；已是 dict 则原样返回。"""
    if dataclasses.is_dataclass(e) and not isinstance(e, type):
        return dataclasses.asdict(e)
    return e


def _default_target_factory(params: dict):
    from qun_alpha.config import load_config
    from qun_alpha import orchestrator, extractor
    cfg = load_config(params.get("config_path", "config.json"))
    dry_run = params.get("dry_run", True)
    client = None
    if not dry_run:
        from notion_client import Client
        client = Client(auth=cfg.notion_token)

    def target(emit):
        return orchestrator.run_job(
            export_path=params["export_path"],
            group_ids=params["group_ids"],
            start=params.get("start", 0),
            end=params.get("end", 2_000_000_000),
            max_messages=cfg.max_messages_per_chunk,
            prompt_version=cfg.prompt_version,
            runner=extractor.default_claude_runner,
            cache_dir=cfg.cache_dir,
            notion_client=client,
            companies_db_id=cfg.notion_companies_db_id,
            people_db_id=cfg.notion_people_db_id,
            links_db_id=cfg.notion_links_db_id,
            dry_run=dry_run,
            emit=emit,
        )
    return target


def create_app(*, manager: Optional[JobManager] = None,
               target_factory: Optional[TargetFactory] = None,
               groups_provider: Optional[GroupsProvider] = None) -> FastAPI:
    manager = manager or JobManager()
    target_factory = target_factory or _default_target_factory
    groups_provider = groups_provider or chat_reader.list_groups
    app = FastAPI(title="群聊投资机会分析")

    @app.get("/api/groups")
    def groups(export_path: str):
        return JSONResponse(groups_provider(export_path))

    @app.post("/api/jobs")
    async def start_job(req: Request):
        params = await req.json()
        job_id = manager.start(target_factory(params))
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "events": [_ev(e) for e in job.events],
        }

    return app
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web.create_app 群列表/起任务/查状态端点"
```

---

## Task 3: SSE 进度流

**Files:**
- Modify: `qun_alpha/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
from qun_alpha.web import iter_sse


def test_iter_sse_replays_events_then_terminal():
    mgr = JobManager()

    def target(emit):
        emit({"stage": "read", "current": 1, "total": 1, "message": "ok"})
        emit({"stage": "extract", "current": 1, "total": 1, "message": "块"})
        return {"companies": 2}

    job_id = mgr.start(target)
    mgr.join(job_id)
    chunks = list(iter_sse(mgr, job_id, poll=0.0))
    text = "".join(chunks)
    # 每个事件都是一行 data: ...\n\n
    assert text.count("data:") >= 3          # 2 个进度 + 1 个终态
    assert '"stage": "read"' in text or '"stage":"read"' in text
    assert '"status": "done"' in text or '"status":"done"' in text


def test_iter_sse_unknown_job():
    chunks = list(iter_sse(JobManager(), "nope", poll=0.0))
    assert any("error" in c for c in chunks)


def test_stream_endpoint_content_type():
    mgr = JobManager()
    client = _client(mgr)
    r = client.post("/api/jobs", json={"export_path": "x.json",
                                       "group_ids": ["g1"], "dry_run": True})
    job_id = r.json()["job_id"]
    mgr.join(job_id)
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert "data:" in body
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: FAIL，`ImportError: cannot import name 'iter_sse'`

- [ ] **Step 3: 修改 `qun_alpha/web.py`**

在文件顶部 import 增加：
```python
import json
import time
```
并把 `from fastapi.responses import JSONResponse` 改为：
```python
from fastapi.responses import JSONResponse, StreamingResponse
```

在 `_ev` 函数后面追加：
```python
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def iter_sse(manager: JobManager, job_id: str, poll: float = 0.05):
    """逐个吐进度事件，job 终态时吐一条终态事件后结束。"""
    sent = 0
    while True:
        job = manager.get(job_id)
        if job is None:
            yield _sse({"stage": "error", "message": "unknown job"})
            return
        while sent < len(job.events):
            yield _sse(_ev(job.events[sent]))
            sent += 1
        if job.status in ("done", "error"):
            yield _sse({"status": job.status, "result": job.result,
                        "error": job.error})
            return
        time.sleep(poll)
```

在 `create_app` 内、`return app` 之前追加路由：
```python
    @app.get("/api/jobs/{job_id}/stream")
    def stream(job_id: str):
        return StreamingResponse(iter_sse(manager, job_id),
                                 media_type="text/event-stream")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web SSE 进度流 iter_sse + /stream 路由"
```

---

## Task 4: 前端单页 + 根路由

**Files:**
- Create: `qun_alpha/static/index.html`
- Modify: `qun_alpha/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
def test_index_served():
    client = _client(JobManager())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'id="groups"' in r.text
    assert "群聊投资机会" in r.text
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_web.py::test_index_served -q`
Expected: FAIL（404，根路由还没实现）

- [ ] **Step 3: 创建 `qun_alpha/static/index.html`**

```html
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊投资机会分析</title>
<style>
  body { font-family: -apple-system, "PingFang SC", sans-serif; max-width: 720px;
         margin: 40px auto; padding: 0 16px; color: #1a1a1a; }
  h1 { font-size: 20px; }
  .row { margin: 12px 0; }
  input[type=text] { width: 100%; padding: 8px; box-sizing: border-box; }
  #groups label { display: block; padding: 4px 0; }
  button { padding: 8px 16px; cursor: pointer; }
  #bar { height: 10px; background: #eee; border-radius: 5px; overflow: hidden; }
  #barfill { height: 100%; width: 0; background: #2d7; transition: width .2s; }
  #log { font-size: 13px; color: #666; white-space: pre-wrap; margin-top: 8px; }
  #result { margin-top: 16px; font-weight: 600; }
</style>
</head>
<body>
<h1>群聊投资机会分析</h1>

<div class="row">
  <label>导出 JSON 路径</label>
  <input type="text" id="export_path" placeholder="exported_chats/all.json">
  <button id="loadGroups">加载群列表</button>
</div>

<div class="row" id="groups"></div>

<div class="row">
  <label><input type="checkbox" id="dry_run" checked> 预演（不写 Notion）</label>
</div>

<div class="row">
  <button id="start">开始分析</button>
</div>

<div class="row"><div id="bar"><div id="barfill"></div></div></div>
<div id="log"></div>
<div id="result"></div>

<script>
const $ = (id) => document.getElementById(id);

$("loadGroups").onclick = async () => {
  const ep = $("export_path").value.trim();
  const res = await fetch("/api/groups?export_path=" + encodeURIComponent(ep));
  const groups = await res.json();
  $("groups").innerHTML = groups.map(g =>
    `<label><input type="checkbox" class="grp" value="${g.group_id}"> ${g.group_name} (${g.count})</label>`
  ).join("");
};

$("start").onclick = async () => {
  const group_ids = [...document.querySelectorAll(".grp:checked")].map(e => e.value);
  $("log").textContent = "";
  $("result").textContent = "";
  $("barfill").style.width = "0";
  const res = await fetch("/api/jobs", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      export_path: $("export_path").value.trim(),
      group_ids, dry_run: $("dry_run").checked,
    }),
  });
  const { job_id } = await res.json();
  const src = new EventSource("/api/jobs/" + job_id + "/stream");
  src.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.stage && d.total) {
      $("barfill").style.width = Math.round(d.current / d.total * 100) + "%";
      $("log").textContent += `[${d.stage}] ${d.message}\n`;
    }
    if (d.status) {
      src.close();
      if (d.status === "error") {
        $("result").textContent = "出错：" + d.error;
      } else {
        const r = d.result || {};
        $("result").textContent =
          `完成：${r.companies||0} 公司 / ${r.people||0} 人 / ${r.links||0} 链接`;
      }
    }
  };
};
</script>
</body>
</html>
```

- [ ] **Step 4: 修改 `qun_alpha/web.py`** 提供根路由

在顶部 import 增加：
```python
from pathlib import Path
from fastapi.responses import HTMLResponse
```
（即把 responses import 行合并为：`from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse`）

在 `create_app` 内、其它路由旁追加：
```python
    @app.get("/")
    def index():
        html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: PASS（7 passed）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/static/index.html qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: 前端单页 + 根路由 serving"
```

---

## Task 5: qun-alpha serve 命令

**Files:**
- Modify: `qun_alpha/cli.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
def test_build_app_returns_fastapi():
    from qun_alpha.cli import build_app
    from fastapi import FastAPI
    app = build_app()
    assert isinstance(app, FastAPI)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_web.py::test_build_app_returns_fastapi -q`
Expected: FAIL，`ImportError: cannot import name 'build_app'`

- [ ] **Step 3: 修改 `qun_alpha/cli.py`** 增加 `build_app` 与 `serve`

在文件末尾 `if __name__ == "__main__":` 之前追加：
```python
def build_app():
    """构造 FastAPI app（供 serve 与测试用）。"""
    from qun_alpha.web import create_app
    return create_app()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(7800),
    open_browser: bool = typer.Option(True, help="启动后自动开浏览器"),
):
    """启动本地 Web 操作台（localhost）。"""
    import threading
    import webbrowser
    import uvicorn
    application = build_app()
    if open_browser:
        url = f"http://{host}:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(application, host=host, port=port)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 跑全套**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（约 50 passed：42 + web 8）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/cli.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: qun-alpha serve 命令 + build_app"
```

---

## 完成标准（Plan 2b-2）

- [ ] `pytest -q` 全绿（约 50 passed）
- [ ] `GET /api/groups`、`POST /api/jobs`、`GET /api/jobs/{id}`、`GET /api/jobs/{id}/stream`(SSE)、`GET /`(前端) 都工作
- [ ] `iter_sse` 可独立测试：回放缓冲事件 + 终态事件
- [ ] 前端单页能选群、起任务、看进度条、看结果
- [ ] `qun-alpha serve` 命令存在，`build_app()` 返回 FastAPI 实例

## 手动验收（用户自测，不进 CI）

1. `cp config.example.json config.json` 并填好 notion_token / 三个 db_id（或先 `qun-alpha init-notion`）
2. 准备一份 wechat-decrypt 导出 JSON（Plan 3 接入后自动产出；此前可手造）
3. `qun-alpha serve` → 浏览器开 http://127.0.0.1:7800 → 填导出路径 → 加载群 → 选群 → 预演开始 → 看进度与结果

## 后续（不在本计划）

- Plan 3：decrypt_service 封装 wechat-decrypt（密钥/解库/导出 JSON，含 sudo+codesign 引导）+ Railway 落地引导页。
- 真实 `claude -p` / 真实 Notion 集成验收。
- 断点续跑（任务状态落盘）、并发抽取、成本预估面板。
