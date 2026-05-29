# Spec C 网页群选择增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 网页群列表加搜索 + 全选/多选 + 已处理状态徽标；落盘每群已分析状态并修"起任务没记录 group_ids"。

**Architecture:** `processed_store`（文件落盘，多实例同文件）记每群 runs/last；`_default_target_factory` 成功后 mark；`/api/groups` 注入 processed 信息；前端搜索过滤 + 全选 + 徽标。

**Tech Stack:** Python（json/os/threading/datetime，stdlib）、FastAPI、原生 JS、pytest。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/processed_store.py   # 新：ProcessedStore.mark/get/all
qun_alpha/web.py               # 改：target 成功后 mark；/api/groups 注入 processed；create_app 加 processed_store 注入
qun_alpha/static/index.html    # 改：搜索框 + 全选 + 已处理徽标
tests/test_processed_store.py / test_web.py（新/改）
```

---

## Task 1: processed_store.py

**Files:** Create `qun_alpha/processed_store.py`; Test `tests/test_processed_store.py`

- [ ] **Step 1: 写失败测试 `tests/test_processed_store.py`**

```python
from qun_alpha.processed_store import ProcessedStore


def test_mark_and_get(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    assert s.get("g1") is None
    s.mark(["g1", "g2"], when="2026-05-29T10:00:00")
    assert s.get("g1") == {"runs": 1, "last": "2026-05-29T10:00:00"}
    assert s.get("g2")["runs"] == 1


def test_mark_increments_runs(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    s.mark(["g1"], when="t1")
    s.mark(["g1"], when="t2")
    assert s.get("g1") == {"runs": 2, "last": "t2"}


def test_multi_instance_same_file(tmp_path):
    p = str(tmp_path / "p.json")
    ProcessedStore(path=p).mark(["g1"], when="t1")
    assert ProcessedStore(path=p).get("g1")["runs"] == 1


def test_all_and_empty_groups(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    s.mark([], when="t1")          # 空列表不报错
    assert s.all() == {}
    s.mark(["g1"], when="t1")
    assert "g1" in s.all()
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_processed_store.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/processed_store.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_processed_store.py -q` → Expected: 4 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/processed_store.py tests/test_processed_store.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: processed_store 每群已分析状态落盘"
```

---

## Task 2: web 接入（标记 + /api/groups 注入）

**Files:** Modify `qun_alpha/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
def test_groups_endpoint_shows_processed(tmp_path):
    from qun_alpha.processed_store import ProcessedStore
    ps = ProcessedStore(path=str(tmp_path / "p.json"))
    ps.mark(["g1"], when="2026-05-29T10:00:00")
    app = create_app(manager=JobManager(),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [
                         {"group_id": "g1", "group_name": "A", "count": 5},
                         {"group_id": "g2", "group_name": "B", "count": 3}],
                     processed_store=ps)
    client = TestClient(app)
    data = client.get("/api/groups", params={"export_path": "x"}).json()
    g1 = next(g for g in data if g["group_id"] == "g1")
    g2 = next(g for g in data if g["group_id"] == "g2")
    assert g1["processed"] is True and g1["runs"] == 1
    assert g2["processed"] is False
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_groups_endpoint_shows_processed -q`
Expected: FAIL（create_app 不认 processed_store / groups 无 processed 字段）

- [ ] **Step 3: 修改 `qun_alpha/web.py`**

(a) 顶部 import 增加：
```python
from qun_alpha.processed_store import ProcessedStore
```

(b) 在 `_default_target_factory` 的 `target` 里，让 run_job 成功后标记已处理。把
```python
    def target(emit):
        return orchestrator.run_job(
```
改为（包一层记录返回值并 mark）：
```python
    def target(emit):
        result = orchestrator.run_job(
```
并在该 `orchestrator.run_job(...)` 调用结束的 `)` 之后、`return target` 之前，把原来的 `return ...` 收尾改为：
找到 target 函数体内 run_job 调用的结尾（`dry_run=dry_run, emit=emit, ... )`），其后改成：
```python
        )
        try:
            ProcessedStore().mark(params.get("group_ids", []))
        except Exception:
            pass
        return result
```
（即：`result = orchestrator.run_job(...)` 然后 mark 再 return result。注意原函数是直接 `return orchestrator.run_job(...)`，改为先赋值给 result、mark、再 return。）

(c) `create_app` 签名加参数（带默认）：在现有参数末尾（`config_loader` 之后）加：
```python
               processed_store: Optional[Any] = None,
```
并在函数开头（其它 `xx = xx or ...` 之后）加：
```python
    processed_store = processed_store or ProcessedStore()
```

(d) 把 `/api/groups` 端点改为注入 processed：
```python
    @app.get("/api/groups")
    def groups(export_path: str):
        out = []
        for g in groups_provider(export_path):
            g = dict(g)
            p = processed_store.get(g["group_id"])
            g["processed"] = bool(p)
            if p:
                g["runs"] = p.get("runs")
                g["last"] = p.get("last")
            out.append(g)
        return JSONResponse(out)
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web 标记已分析群 + /api/groups 注入 processed"
```

---

## Task 3: 前端搜索 + 全选 + 已处理徽标

**Files:** Modify `qun_alpha/static/index.html`; Test `tests/test_web.py`

- [ ] **Step 1: 追加 smoke 测试到 `tests/test_web.py` 末尾**

```python
def test_index_has_group_search_and_selectall():
    client = _client(JobManager())
    html = client.get("/").text
    assert 'id="groupSearch"' in html
    assert 'id="selectAll"' in html
    assert "已分析" in html          # 徽标文案
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_index_has_group_search_and_selectall -q` → Expected: FAIL

- [ ] **Step 3: 修改 `qun_alpha/static/index.html`**

(a) 找到群卡片：
```html
<div class="card" id="groupsCard" style="display:none">
  <label>选择群</label>
  <div id="groups"></div>
</div>
```
替换为（加搜索框 + 全选按钮）：
```html
<div class="card" id="groupsCard" style="display:none">
  <div class="row" style="justify-content:space-between">
    <label>选择群</label>
    <button id="selectAll" class="ghost" style="padding:4px 10px;font-size:12px">全选/全不选</button>
  </div>
  <input type="text" id="groupSearch" placeholder="搜索群名…" style="margin:8px 0">
  <div id="groups"></div>
</div>
```

(b) 在 `<script>` 里，把 `loadGroups` 的渲染那行（`$("groups").innerHTML=groups.map(...)`）替换为带徽标的版本：
```javascript
    $("groups").innerHTML=groups.map(g=>{
      const badge = g.processed ? ` <span class="muted" style="color:var(--green)">✓已分析·${g.runs||1}次</span>` : "";
      return `<label class="grpitem"><input type="checkbox" class="grp" value="${g.group_id}"> ${g.group_name} <span class="muted">(${g.count})</span>${badge}</label>`;
    }).join("");
```

(c) 在 `loadGroups` 定义之后，追加搜索过滤 + 全选逻辑：
```javascript
$("groupSearch").oninput=()=>{
  const q=$("groupSearch").value.trim().toLowerCase();
  document.querySelectorAll("#groups .grpitem").forEach(el=>{
    el.style.display = el.textContent.toLowerCase().includes(q) ? "flex" : "none";
  });
};
$("selectAll").onclick=()=>{
  const vis=[...document.querySelectorAll("#groups .grpitem")].filter(el=>el.style.display!=="none");
  const boxes=vis.map(el=>el.querySelector(".grp"));
  const allOn=boxes.every(b=>b.checked);
  boxes.forEach(b=>b.checked=!allOn);   // 对当前可见项全选/全不选
};
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过（含新 smoke）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/static/index.html tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: 网页群搜索+全选+已分析徽标"
```

---

## 完成标准（Spec C）
- [ ] `pytest -q` 全绿
- [ ] `processed_store` mark/get/all、runs 累加、多实例同文件
- [ ] `/api/groups` 每群带 `processed`(/runs/last)
- [ ] 分析成功后该批 group_ids 被标记已处理（_default_target_factory）
- [ ] 网页有搜索框 + 全选 + 已分析徽标
- [ ] 既有测试不回归

## 后续（不在 C）
- 单群机会数；服务端分页；结合 cursor 显示"有新消息待分析"。
