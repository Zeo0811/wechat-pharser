# 本地报告输出（Word+MD 到 Downloads，移除 Notion/预演）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分析结束后直接在 `~/Downloads` 生成 Word(.docx)+Markdown(.md) 两份报告，并把 Notion 写入与"预演"开关移出主流程。

**Architecture:** 新增 `report.py`（纯函数，吃聚合后的 Company/Person/Link 模型，产出 md 字符串 + docx 文件）。`orchestrator.run_job` 聚合后调用它，result 用 `report_md`/`report_docx` 取代三个 `*_payloads`，并删除 notion 写入与 `dry_run` 参数。cli/web 同步去掉 notion/dry_run、加 `report_dir`。前端删除"预演"勾选、完成时显示保存路径。notion_writer 模块与 `init-notion` 命令保留备用，不在流程里调。

**Tech Stack:** Python 3.10+，pydantic v2，python-docx，FastAPI，pytest。

**约定：** 仓库测试用 `~/qun-alpha/.venv/bin/python -m pytest`（下文 `pytest` 均指它）。每个 Task 完成后单独 commit。

---

### Task 1: report.py + python-docx 依赖

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `python-docx`）
- Create: `qun_alpha/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: 加依赖并装上**

在 `pyproject.toml` 的 `dependencies = [ ... ]` 列表里加一行（与现有条目同缩进、同引号风格）：

```
    "python-docx>=1.1,<2",
```

然后装进仓库 venv：

Run: `cd ~/qun-alpha && .venv/bin/pip install -q "python-docx>=1.1,<2"`
Expected: 安装成功，`.venv/bin/python -c "import docx; print(docx.__version__)"` 打印版本号。

- [ ] **Step 2: 写失败测试**

创建 `tests/test_report.py`：

```python
import os
import zipfile
from qun_alpha.models import Company, Person, Link, SourceRef
from qun_alpha import report


def _src():
    return SourceRef(group_name="AI投资群", sender="老王",
                     timestamp=1716700000, msg_id="m1")


def _sample():
    companies = [
        Company(name="IrisGo", score=72, mentions=3, status="emerging",
                signal="拿了$2.8M种子轮 · under-the-radar AI seed",
                first_seen=1716700000, last_seen=1716700050,
                sector="AI", stage="种子轮", financials="$2.8M 种子轮",
                investors=["AI Fund"], suggested_action="约创始人聊一次",
                confidence=0.8, related_people=["老王"], sources=[_src()]),
        Company(name="低分公司", score=10, mentions=1, status="noise",
                signal="一句带过", first_seen=1716700000, last_seen=1716700000,
                sources=[_src()]),
    ]
    people = [
        Person(name="老王", mentions=2, role="投资人",
               affiliated_companies=["AI Fund"],
               notable_quotes=["这个赛道还早"], sources=[_src()]),
    ]
    links = [
        Link(url="https://example.com/irisgo", title="IrisGo 报道",
             shared_by=["老王"], related_companies=["IrisGo"],
             first_seen=1716700000, sources=[_src()]),
    ]
    return companies, people, links


def test_build_markdown_contains_key_content():
    companies, people, links = _sample()
    md = report.build_markdown(companies, people, links)
    assert "IrisGo" in md
    assert "拿了$2.8M种子轮" in md          # signal 落地
    assert "老王" in md
    assert "https://example.com/irisgo" in md
    # 公司按 score 降序：高分在低分之前
    assert md.index("IrisGo") < md.index("低分公司")


def test_write_reports_creates_both_files(tmp_path):
    companies, people, links = _sample()
    paths = report.write_reports(companies, people, links,
                                 out_dir=str(tmp_path), when="2026-05-31_120000")
    assert paths["md"] == os.path.join(str(tmp_path), "群聊投资机会_2026-05-31_120000.md")
    assert paths["docx"] == os.path.join(str(tmp_path), "群聊投资机会_2026-05-31_120000.docx")
    assert os.path.exists(paths["md"])
    assert os.path.exists(paths["docx"])
    # md 内容
    assert "IrisGo" in open(paths["md"], encoding="utf-8").read()
    # docx 是合法 zip 且正文含公司名
    assert zipfile.is_zipfile(paths["docx"])
    with zipfile.ZipFile(paths["docx"]) as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
    assert "IrisGo" in doc_xml


def test_write_reports_default_dir_is_downloads(tmp_path, monkeypatch):
    # 不传 out_dir 时落到 ~/Downloads（用 HOME 重定向验证，不污染真实 Downloads）
    monkeypatch.setenv("HOME", str(tmp_path))
    companies, people, links = _sample()
    paths = report.write_reports(companies, people, links, when="2026-05-31_120000")
    assert paths["md"].startswith(os.path.join(str(tmp_path), "Downloads"))
    assert os.path.exists(paths["md"])
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_report.py -v`
Expected: FAIL（`module qun_alpha has no attribute report` / ImportError）。

- [ ] **Step 4: 实现 report.py**

创建 `qun_alpha/report.py`：

```python
from __future__ import annotations
import os
from typing import Optional
from qun_alpha.models import Company, Person, Link


def _company_block_lines(c: Company) -> list[str]:
    lines = [f"### 【{c.score}·{c.status}】{c.name}  ·  {c.mentions} 次提及"]
    meta = []
    if c.sector:
        meta.append(f"赛道：{c.sector}")
    if c.stage:
        meta.append(f"阶段：{c.stage}")
    if c.financials:
        meta.append(f"融资：{c.financials}")
    if c.investors:
        meta.append(f"投资方：{', '.join(c.investors)}")
    if meta:
        lines.append("- " + " · ".join(meta))
    if c.suggested_action:
        lines.append(f"- 建议：{c.suggested_action}")
    if c.signal:
        lines.append(f"- Signal：{c.signal}")
    return lines


def _person_line(p: Person) -> str:
    bits = [p.name]
    if p.role:
        bits.append(f"（{p.role}）")
    extra = []
    if p.affiliated_companies:
        extra.append("关联：" + "、".join(p.affiliated_companies))
    if p.notable_quotes:
        extra.append("金句：" + "；".join(p.notable_quotes))
    tail = ("  ·  " + "  ·  ".join(extra)) if extra else ""
    return f"- {''.join(bits)}{tail}（{p.mentions} 次）"


def _link_line(ln: Link) -> str:
    title = ln.title or ln.url
    extra = []
    if ln.related_companies:
        extra.append("关联：" + "、".join(ln.related_companies))
    if ln.shared_by:
        extra.append("分享：" + "、".join(ln.shared_by))
    tail = ("  ·  " + "  ·  ".join(extra)) if extra else ""
    return f"- [{title}]({ln.url}){tail}"


def build_markdown(companies: list[Company], people: list[Person],
                   links: list[Link]) -> str:
    companies = sorted(companies, key=lambda c: c.score, reverse=True)
    out = ["# 群聊投资机会报告", ""]
    out.append(f"共 {len(companies)} 公司 / {len(people)} 人 / {len(links)} 链接")
    out.append("")
    out.append("## 一、公司")
    out.append("")
    if companies:
        for c in companies:
            out.extend(_company_block_lines(c))
            out.append("")
    else:
        out.append("（无）")
        out.append("")
    out.append("## 二、人物")
    out.append("")
    out.extend([_person_line(p) for p in people] or ["（无）"])
    out.append("")
    out.append("## 三、链接")
    out.append("")
    out.extend([_link_line(ln) for ln in links] or ["（无）"])
    out.append("")
    return "\n".join(out)


def _build_docx(companies: list[Company], people: list[Person],
                links: list[Link], path: str) -> None:
    from docx import Document
    companies = sorted(companies, key=lambda c: c.score, reverse=True)
    doc = Document()
    doc.add_heading("群聊投资机会报告", level=0)
    doc.add_paragraph(f"共 {len(companies)} 公司 / {len(people)} 人 / {len(links)} 链接")

    doc.add_heading("一、公司", level=1)
    for c in companies:
        doc.add_heading(f"【{c.score}·{c.status}】{c.name}  ·  {c.mentions} 次提及", level=2)
        meta = []
        if c.sector:
            meta.append(f"赛道：{c.sector}")
        if c.stage:
            meta.append(f"阶段：{c.stage}")
        if c.financials:
            meta.append(f"融资：{c.financials}")
        if c.investors:
            meta.append(f"投资方：{', '.join(c.investors)}")
        if meta:
            doc.add_paragraph(" · ".join(meta))
        if c.suggested_action:
            doc.add_paragraph(f"建议：{c.suggested_action}")
        if c.signal:
            doc.add_paragraph(f"Signal：{c.signal}")

    doc.add_heading("二、人物", level=1)
    for p in people:
        role = f"（{p.role}）" if p.role else ""
        line = f"{p.name}{role} · {p.mentions} 次"
        if p.affiliated_companies:
            line += "　关联：" + "、".join(p.affiliated_companies)
        if p.notable_quotes:
            line += "　金句：" + "；".join(p.notable_quotes)
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("三、链接", level=1)
    for ln in links:
        title = ln.title or ln.url
        line = f"{title} — {ln.url}"
        if ln.related_companies:
            line += "　关联：" + "、".join(ln.related_companies)
        if ln.shared_by:
            line += "　分享：" + "、".join(ln.shared_by)
        doc.add_paragraph(line, style="List Bullet")

    doc.save(path)


def write_reports(companies: list[Company], people: list[Person],
                  links: list[Link], out_dir: Optional[str] = None,
                  when: Optional[str] = None) -> dict:
    """生成 md + docx 两份报告，返回 {"md": path, "docx": path}。"""
    out_dir = out_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(out_dir, exist_ok=True)
    if when is None:
        from datetime import datetime
        when = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    md_path = os.path.join(out_dir, f"群聊投资机会_{when}.md")
    docx_path = os.path.join(out_dir, f"群聊投资机会_{when}.docx")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_markdown(companies, people, links))
    _build_docx(companies, people, links, docx_path)
    return {"md": md_path, "docx": docx_path}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_report.py -v`
Expected: 4 passed。

- [ ] **Step 6: Commit**

```bash
cd ~/qun-alpha && git add pyproject.toml qun_alpha/report.py tests/test_report.py
git commit -m "feat: report.py 生成 Word+Markdown 报告（python-docx）"
```

---

### Task 2: orchestrator.run_job 改为生成报告、移除 Notion/dry_run

**Files:**
- Modify: `qun_alpha/orchestrator.py:1-31`（import + 签名）、`:72-90`（写入块 + result）
- Test: `tests/test_orchestrator.py`（更新 `_run` 与断言）

- [ ] **Step 1: 改 test_orchestrator.py 的 `_run` 与断言（先让测试表达新契约）**

把 `tests/test_orchestrator.py` 顶部 import 行
`from qun_alpha.orchestrator import run_job, ProgressEvent`
保持不变。将 `_run` 函数整体替换为：

```python
def _run(tmp_path):
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        report_dir=str(tmp_path / "reports"), emit=events.append,
    )
    return events, result
```

将 `test_run_job_returns_same_shape_as_pipeline` 整体替换为：

```python
def test_run_job_returns_same_shape_as_pipeline(tmp_path):
    import os
    events, result = _run(tmp_path)
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert os.path.exists(result["report_md"])
    assert os.path.exists(result["report_docx"])
    assert set(result.keys()) >= {
        "chunks", "raw_entities", "companies", "people", "links",
        "report_md", "report_docx"}
    assert "company_payloads" not in result
    # 仍然吐 write 与 done 阶段
    stages = {e.stage for e in events}
    assert "write" in stages and "done" in stages
```

- [ ] **Step 2: 看 test_orchestrator 其余用例是否还传 notion 参数**

Run: `cd ~/qun-alpha && grep -n "notion_client\|dry_run\|companies_db_id\|people_db_id\|links_db_id\|company_payloads" tests/test_orchestrator.py`
Expected: 若除 `_run` 外的其它用例（如 `test_run_job_records_progress_to_store`、增量用例）仍含这些词，逐个把 `notion_client=None, companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb", dry_run=True,` 整段删除，并在该 `run_job(...)` 调用里补上 `report_dir=str(tmp_path / "reports"),`；删除任何对 `result["company_payloads"]` 的断言。改完此命令应无残留（除注释外）。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL（run_job 仍要求 notion 参数 / 返回 company_payloads / 无 report_md）。

- [ ] **Step 4: 改 orchestrator.py — import 与签名**

把第 5 行
```python
from qun_alpha import chat_reader, extractor, aggregator, notion_writer
```
改为
```python
from qun_alpha import chat_reader, extractor, aggregator, report
```

把 `run_job` 签名（第 23-31 行）整体替换为：

```python
def run_job(*, export_path: str, group_ids: list[str], start: int, end: int,
            max_messages: int, prompt_version: str,
            runner: Callable[[str], str], cache_dir: Optional[str],
            report_dir: Optional[str] = None, emit: Emit = _noop,
            concurrency: int = 3, job_store: Any = None,
            job_id: Optional[str] = None,
            incremental: bool = False, cursor_store: Any = None) -> dict:
```

- [ ] **Step 5: 改 orchestrator.py — 写入块与 result**

把第 72-90 行（从 `emit(ProgressEvent("write", 0, 1, "写 Notion"))` 到 result 字典闭合 `}`）整体替换为：

```python
    emit(ProgressEvent("write", 0, 1, "生成报告"))
    paths = report.write_reports(companies, people, links, out_dir=report_dir)
    emit(ProgressEvent("write", 1, 1, f"已保存：{paths['md']}"))

    result = {
        "chunks": total,
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "report_md": paths["md"],
        "report_docx": paths["docx"],
    }
```

（其后的增量游标块 `if incremental and cursor_store is not None:` 与 `emit(... "done" ...)`、`return result` 保持不变。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_orchestrator.py -v`
Expected: 全部 passed。

- [ ] **Step 7: Commit**

```bash
cd ~/qun-alpha && git add qun_alpha/orchestrator.py tests/test_orchestrator.py
git commit -m "refactor: run_job 改为生成报告并移除 Notion/dry_run"
```

---

### Task 3: cli run_pipeline + analyze 去 Notion/dry_run、加 report_dir

**Files:**
- Modify: `qun_alpha/cli.py:11-24`（run_pipeline）、`:32-62`（analyze）
- Test: `tests/test_cli_smoke.py`

- [ ] **Step 1: 改 test_cli_smoke.py 表达新契约**

将 `test_run_pipeline_end_to_end` 整体替换为：

```python
def test_run_pipeline_end_to_end(tmp_path):
    import os
    result = run_pipeline(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"],
        start=0, end=2_000_000_000,
        max_messages=1,
        prompt_version="v1",
        runner=_fake_runner,
        cache_dir=str(tmp_path / "cache"),
        report_dir=str(tmp_path / "reports"),
    )
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["people"] >= 1
    assert os.path.exists(result["report_md"])
    assert os.path.exists(result["report_docx"])
    assert "company_payloads" not in result
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_cli_smoke.py -v`
Expected: FAIL（run_pipeline 仍需 notion_client/dry_run）。

- [ ] **Step 3: 改 cli.run_pipeline（第 11-24 行整体替换）**

```python
def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 report_dir: Optional[str] = None) -> dict:
    return orchestrator.run_job(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=max_messages, prompt_version=prompt_version,
        runner=runner, cache_dir=cache_dir, report_dir=report_dir,
    )
```

- [ ] **Step 4: 改 analyze 命令（第 32-62 行整体替换）**

```python
@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒（默认≈2033，等于无上界）"),
    config_path: str = typer.Option("config.json"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="报告输出目录（默认 ~/Downloads）"),
    model: str = typer.Option(None, "--model", help="本次用哪个后端: claude / codex"),
):
    """分析指定群的指定时间段，在 ~/Downloads 生成 Word+Markdown 报告。"""
    import os
    cfg = load_config(config_path)
    backend = model or cfg.model_backend
    runners.ensure_available(backend)   # CLI 不在 PATH → 提前人话报错
    report_dir = out_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    result = run_pipeline(
        export_path=export_path,
        group_ids=[g.strip() for g in groups.split(",") if g.strip()],
        start=start, end=end,
        max_messages=cfg.max_messages_per_chunk,
        prompt_version=cfg.prompt_version,
        runner=runners.get_runner(backend),
        cache_dir=cfg.cache_dir,
        report_dir=report_dir,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")
    typer.echo(f"已保存报告：{result['report_md']}")
    typer.echo(f"            {result['report_docx']}")
```

注意：`_notion_client` 辅助函数与 `init-notion` 命令**保留不动**（备用）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest tests/test_cli_smoke.py -v`
Expected: passed。

- [ ] **Step 6: Commit**

```bash
cd ~/qun-alpha && git add qun_alpha/cli.py tests/test_cli_smoke.py
git commit -m "refactor: cli analyze/run_pipeline 输出报告，去 Notion/dry_run"
```

---

### Task 4: web 工厂去 Notion/dry_run + 前端删"预演"、显示报告路径

**Files:**
- Modify: `qun_alpha/web.py:48-86`（`_default_target_factory`）
- Modify: `qun_alpha/static/index.html:66-76`（删 dry_run 勾选）、`:184-215`（POST body 去 dry_run、完成时显示路径）
- Test: `tests/test_web.py`（确认不依赖旧字段）

- [ ] **Step 1: 改 `_default_target_factory`（第 48-86 行整体替换）**

```python
def _default_target_factory(params: dict):
    import os
    from qun_alpha.config import load_config
    cfg = load_config(params.get("config_path", "config.json"))
    incremental = params.get("incremental", False)
    concurrency = int(params.get("concurrency", 3))
    cursor = CursorStore()
    backend = params.get("model") or cfg.model_backend
    # 抽取要调模型 CLI，先确认它在；缺失 → start_job 返回 400
    runners.ensure_available(backend)
    report_dir = params.get("report_dir") or os.path.join(
        os.path.expanduser("~"), "Downloads")

    def target(emit):
        result = orchestrator.run_job(
            export_path=params["export_path"],
            group_ids=params["group_ids"],
            start=params.get("start", 0),
            end=params.get("end", 2_000_000_000),
            max_messages=cfg.max_messages_per_chunk,
            prompt_version=cfg.prompt_version,
            runner=runners.get_runner(backend),
            cache_dir=cfg.cache_dir,
            report_dir=report_dir, emit=emit,
            concurrency=concurrency,
            incremental=incremental, cursor_store=cursor,
        )
        try:
            ProcessedStore().mark(params.get("group_ids", []))
        except Exception:
            pass
        return result
    return target
```

- [ ] **Step 2: 前端删除"预演"勾选（index.html 第 66-70 行）**

把
```html
  <div class="row">
    <label><input type="checkbox" id="incremental"> 增量（只分析上次之后的新消息）</label>
    <label><input type="checkbox" id="dry_run" checked> 预演（不写 Notion）</label>
  </div>
```
替换为
```html
  <div class="row">
    <label><input type="checkbox" id="incremental"> 增量（只分析上次之后的新消息）</label>
    <span class="muted">分析完成后报告自动存到 ~/Downloads（Word + Markdown）</span>
  </div>
```

- [ ] **Step 3: 前端 POST body 去掉 dry_run（index.html 第 192-193 行）**

把
```javascript
      body:JSON.stringify({export_path:CFG.ep,group_ids,
        dry_run:$("dry_run").checked,incremental:$("incremental").checked})});
```
替换为
```javascript
      body:JSON.stringify({export_path:CFG.ep,group_ids,
        incremental:$("incremental").checked})});
```

- [ ] **Step 4: 前端完成时显示报告路径（index.html 第 210-212 行）**

把
```javascript
      if(d.status==="error"){$("result").textContent="出错："+d.error;}
      else{const r=d.result||{};$("result").textContent=`完成：${r.companies||0} 公司 / ${r.people||0} 人 / ${r.links||0} 链接`;}
```
替换为
```javascript
      if(d.status==="error"){$("result").textContent="出错："+d.error;}
      else{const r=d.result||{};
        let t=`完成：${r.companies||0} 公司 / ${r.people||0} 人 / ${r.links||0} 链接`;
        if(r.report_md){t+=`\n已保存到 ~/Downloads：\n${r.report_md}\n${r.report_docx}`;}
        $("result").style.whiteSpace="pre-wrap";$("result").textContent=t;}
```

- [ ] **Step 5: 跑全量测试**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest -q`
Expected: 全绿。若 `tests/test_web.py` 有用例 mock target_factory 返回带 `company_payloads` 的假 result 或断言 dry_run，更新为返回/断言 `report_md`/`report_docx`；若它用自定义 target_factory（不走 `_default_target_factory`）则通常无需改。

- [ ] **Step 6: 冒烟确认前端不含"预演"**

Run: `cd ~/qun-alpha && grep -c "预演\|dry_run" qun_alpha/static/index.html`
Expected: `0`。

- [ ] **Step 7: Commit**

```bash
cd ~/qun-alpha && git add qun_alpha/web.py qun_alpha/static/index.html tests/test_web.py
git commit -m "refactor: web/前端去预演与Notion，完成显示报告路径"
```

---

### Task 5: 全量回归 + 合并到本地 main

- [ ] **Step 1: 全量测试**

Run: `cd ~/qun-alpha && .venv/bin/python -m pytest -q`
Expected: 全绿（约 120+ passed）。

- [ ] **Step 2: 确认 grep 干净**

Run: `cd ~/qun-alpha && grep -rn "dry_run" qun_alpha/orchestrator.py qun_alpha/cli.py qun_alpha/web.py qun_alpha/static/index.html`
Expected: 无输出（notion_writer.py 与 init-notion 不在此列，保留）。

- [ ] **Step 3: 合并回本地 main（不 push，按用户 Git 工作流）**

```bash
cd ~/qun-alpha && git checkout main && git merge --no-ff plan-local-report -m "feat: 本地 Word+MD 报告输出，移除 Notion/预演" && git branch -d plan-local-report
```

- [ ] **Step 4: 告知用户验证点**

main 已更新；提示用户：可 `qun-alpha serve` 起操作台跑一次真实分析，验证 `~/Downloads/群聊投资机会_<时间>.md/.docx` 生成与内容。push 到 GitHub 等用户确认后再做。

---

## Self-Review

**Spec coverage：**
- 去"预演"勾选 → Task 4 Step 2 ✓
- Word+MD 到 ~/Downloads → Task 1（report.py）+ Task 2（run_job 调用）✓
- Notion 移出流程、代码保留 → Task 2（run_job 去 notion）+ Task 3（保留 init-notion/_notion_client）✓
- 文件名 `群聊投资机会_<datetime>` → Task 1 write_reports ✓
- result 带报告路径、前端显示 → Task 2 + Task 4 Step 4 ✓
- python-docx 依赖 → Task 1 Step 1 ✓
- 更新受影响测试 → Task 2/3/4 ✓
- 增量逻辑保留 → Task 2 Step 4-5（未动增量块）✓

**Placeholder scan：** 无 TBD/TODO；每个改代码步骤都给了完整代码块。Task 2 Step 2 与 Task 4 Step 5 含条件式"若…则改"，因依赖现有测试文件的实际内容，已给出明确判定命令（grep）与改法。

**Type consistency：** `write_reports(companies, people, links, out_dir=None, when=None) -> {"md","docx"}` 在 Task 1 定义，Task 2 以 `out_dir=report_dir` 调用、取 `paths["md"]/paths["docx"]`，result 键 `report_md`/`report_docx` 在 Task 2 定义，Task 3/4 测试与前端一致引用。`build_markdown` 签名一致。
