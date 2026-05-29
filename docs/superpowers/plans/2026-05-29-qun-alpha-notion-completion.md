# 群聊投资机会分析 — Notion 完成度 (Plan 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 notion_writer 从 create-only 升级为真正的 upsert（先查后建/更新），补齐 People / Links 两张表的写入，并提供一次性建库命令；最后把 People/Links 接进 cli 管线。

**Architecture:** 复用 Plan 1 已合并的纯函数管线。所有写入走一个共享的 `_upsert_all` helper：dry_run 仍只返回 payload（保持 Plan 1 行为不变），实跑则先用 `databases.query` 按标题查存量页，命中则 `pages.update`，否则 `pages.create`。client 依赖注入，测试用 fake，不碰真 Notion。

**Tech Stack:** Python 3.10+，pydantic v2，notion-client，pytest。沿用 `~/qun-alpha/.venv`，测试用 `.venv/bin/pytest`。

---

## 背景：要修的缺口

Plan 1 final review 指出 `write_companies` 永远 `create`，重复跑会建重复页。Plan 2a 把它改成 upsert，并把当前只写 Companies 扩成 Companies + People + Links 三张表，与 spec 的数据模型对齐。

## File Structure

```
qun_alpha/
  notion_writer.py     # 改：companies upsert；增：people/links 映射+写入、_upsert_all、_find_page_id、ensure_databases
  cli.py               # 改：run_pipeline 接 people/links 写入；增：init-notion 命令
tests/
  test_notion_writer.py  # 改：companies 改测 upsert；增：people/links/ensure_databases 测试
  test_cli_smoke.py      # 改：断言 people/links payload
```

现有 `Company/Person/Link` 模型字段（Plan 1 已实现，供映射参考）：
- Company: name, score, mentions, status, signal, first_seen, last_seen, sector, stage, financials, investors[], sentiment, catalyst, risk, suggested_action, confidence, related_people[], sources[]
- Person: name, mentions, role, affiliated_companies[], notable_quotes[], sources[]
- Link: url, title, shared_by[], related_companies[], first_seen, sources[]

---

## Task 1: Companies 改为 upsert（共享 helper）

**Files:**
- Modify: `qun_alpha/notion_writer.py`
- Test: `tests/test_notion_writer.py`

- [ ] **Step 1: 改写测试 `tests/test_notion_writer.py`**（整文件替换为下面内容）

```python
from qun_alpha.models import Company, SourceRef
from qun_alpha.notion_writer import company_to_properties, write_companies


def _company(name="IrisGo", score=72, status="emerging"):
    return Company(
        name=name, score=score, mentions=2, status=status,
        signal="拿了$2.8M种子轮 — under-the-radar AI seed",
        first_seen=1716700000, last_seen=1716786400,
        sector="AI", stage="种子", financials="$2.8M 种子轮",
        investors=["AI Fund", "拾象"], confidence=0.8,
        sources=[SourceRef(group_name="AI投资群", sender="老王",
                           timestamp=1716700000, msg_id="m1")],
    )


class _Pages:
    def __init__(self, store):
        self._store = store
    def create(self, **kw):
        self._store["created"].append(kw)
        return {"id": "newpage"}
    def update(self, **kw):
        self._store["updated"].append(kw)
        return {"id": kw["page_id"]}


class _Databases:
    def __init__(self, existing_id):
        self._existing_id = existing_id
        self.queries = []
    def query(self, **kw):
        self.queries.append(kw)
        if self._existing_id:
            return {"results": [{"id": self._existing_id}]}
        return {"results": []}


class FakeClient:
    """existing_id=None → 库里没有，应走 create；否则走 update。"""
    def __init__(self, existing_id=None):
        self._store = {"created": [], "updated": []}
        self.pages = _Pages(self._store)
        self.databases = _Databases(existing_id)
    @property
    def created(self):
        return self._store["created"]
    @property
    def updated(self):
        return self._store["updated"]


def test_company_to_properties_maps_fields():
    props = company_to_properties(_company())
    assert props["Company"]["title"][0]["text"]["content"] == "IrisGo"
    assert props["Score"]["number"] == 72
    assert props["Status"]["select"]["name"] == "emerging"
    assert props["Mntns"]["number"] == 2
    assert "拿了$2.8M" in props["Signal"]["rich_text"][0]["text"]["content"]


def test_write_companies_dry_run_does_not_call_api():
    class BoomClient:
        class pages:
            @staticmethod
            def create(**kw):
                raise AssertionError("dry_run 不应调用 API")
        class databases:
            @staticmethod
            def query(**kw):
                raise AssertionError("dry_run 不应调用 API")
    payloads = write_companies([_company()], client=BoomClient(),
                               database_id="db1", dry_run=True)
    assert len(payloads) == 1
    assert payloads[0]["parent"]["database_id"] == "db1"


def test_write_companies_creates_when_absent():
    client = FakeClient(existing_id=None)
    out = write_companies([_company()], client=client,
                          database_id="db1", dry_run=False)
    assert len(client.created) == 1
    assert client.created[0]["parent"]["database_id"] == "db1"
    assert client.updated == []
    assert out == ["newpage"]
    # 查询用了标题等值过滤
    assert client.databases.queries[0]["database_id"] == "db1"


def test_write_companies_updates_when_present():
    client = FakeClient(existing_id="oldpage")
    out = write_companies([_company()], client=client,
                          database_id="db1", dry_run=False)
    assert client.created == []
    assert len(client.updated) == 1
    assert client.updated[0]["page_id"] == "oldpage"
    assert out == ["oldpage"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: FAIL（新测试 `test_write_companies_creates_when_absent` / `_updates_when_present` 失败：当前 `write_companies` 不会调用 `databases.query`，且无 update 分支）

- [ ] **Step 3: 改写 `qun_alpha/notion_writer.py`**（整文件替换为下面内容）

```python
from __future__ import annotations
from typing import Any, Callable
from qun_alpha.models import Company


def _rt(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text[:2000]}}]}


def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def company_to_properties(c: Company) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Company": _title(c.name),
        "Score": {"number": c.score},
        "Mntns": {"number": c.mentions},
        "Status": {"select": {"name": c.status}},
        "Signal": _rt(c.signal),
        "Confidence": {"number": c.confidence},
    }
    if c.sector:
        props["Sector"] = {"select": {"name": c.sector}}
    if c.stage:
        props["Stage"] = {"select": {"name": c.stage}}
    if c.financials:
        props["Financials"] = _rt(c.financials)
    if c.investors:
        props["Investors"] = {"multi_select": [{"name": i[:100]} for i in c.investors]}
    if c.suggested_action:
        props["Action"] = {"select": {"name": c.suggested_action}}
    return props


def _find_page_id(client: Any, database_id: str, title_prop: str,
                  title_value: str):
    """按标题等值查存量页，命中返回 page_id，否则 None。"""
    resp = client.databases.query(
        database_id=database_id,
        filter={"property": title_prop, "title": {"equals": title_value}},
    )
    results = resp.get("results", [])
    return results[0]["id"] if results else None


def _upsert_all(items: list, client: Any, database_id: str, title_prop: str,
                name_of: Callable[[Any], str],
                to_props: Callable[[Any], dict], dry_run: bool) -> list:
    """dry_run 只返回 payload；实跑先查后 update/create。"""
    results: list = []
    for it in items:
        props = to_props(it)
        if dry_run:
            results.append({"parent": {"database_id": database_id},
                            "properties": props})
            continue
        existing = _find_page_id(client, database_id, title_prop, name_of(it))
        if existing:
            client.pages.update(page_id=existing, properties=props)
            results.append(existing)
        else:
            page = client.pages.create(
                parent={"database_id": database_id}, properties=props)
            results.append(page["id"])
    return results


def write_companies(companies: list[Company], client: Any, database_id: str,
                    dry_run: bool = False) -> list[Any]:
    return _upsert_all(companies, client, database_id, "Company",
                       lambda c: c.name, company_to_properties, dry_run)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 跑全套确认无回归**

Run: `.venv/bin/pytest -q`
Expected: PASS（仍 26 passed —— cli 冒烟用 dry_run，行为不变）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/notion_writer.py tests/test_notion_writer.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: notion_writer companies 改为真 upsert (先查后建/更新)"
```

---

## Task 2: People 表写入

**Files:**
- Modify: `qun_alpha/notion_writer.py`
- Test: `tests/test_notion_writer.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_notion_writer.py` 末尾**

```python
from qun_alpha.models import Person
from qun_alpha.notion_writer import person_to_properties, write_people


def _person():
    return Person(
        name="梦琪", mentions=2, role="创始人",
        affiliated_companies=["invoko.ai"],
        notable_quotes=["一个AI创始人", "虚荣心、装"],
        sources=[SourceRef(group_name="AI投资群", sender="小李",
                           timestamp=1716700000, msg_id="p1")],
    )


def test_person_to_properties_maps_fields():
    props = person_to_properties(_person())
    assert props["Person"]["title"][0]["text"]["content"] == "梦琪"
    assert props["Mntns"]["number"] == 2
    assert props["Role"]["rich_text"][0]["text"]["content"] == "创始人"
    assert props["Affiliated"]["multi_select"][0]["name"] == "invoko.ai"
    assert "一个AI创始人" in props["Quotes"]["rich_text"][0]["text"]["content"]


def test_write_people_creates_when_absent():
    client = FakeClient(existing_id=None)
    out = write_people([_person()], client=client,
                       database_id="pdb", dry_run=False)
    assert len(client.created) == 1
    assert out == ["newpage"]


def test_write_people_dry_run():
    payloads = write_people([_person()], client=None,
                            database_id="pdb", dry_run=True)
    assert payloads[0]["parent"]["database_id"] == "pdb"
    assert payloads[0]["properties"]["Person"]["title"][0]["text"]["content"] == "梦琪"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: FAIL，`ImportError: cannot import name 'person_to_properties'`

- [ ] **Step 3: 在 `qun_alpha/notion_writer.py` 顶部 import 增加 Person，并在文件末尾追加：**

把第一行 import 改为：
```python
from qun_alpha.models import Company, Person
```

文件末尾追加：
```python
def person_to_properties(p: Person) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Person": _title(p.name),
        "Mntns": {"number": p.mentions},
    }
    if p.role:
        props["Role"] = _rt(p.role)
    if p.affiliated_companies:
        props["Affiliated"] = {
            "multi_select": [{"name": c[:100]} for c in p.affiliated_companies]}
    if p.notable_quotes:
        props["Quotes"] = _rt(" | ".join(p.notable_quotes))
    return props


def write_people(people: list[Person], client: Any, database_id: str,
                 dry_run: bool = False) -> list[Any]:
    return _upsert_all(people, client, database_id, "Person",
                       lambda p: p.name, person_to_properties, dry_run)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/notion_writer.py tests/test_notion_writer.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: notion_writer 写入 People 表 (upsert)"
```

---

## Task 3: Links 表写入

**Files:**
- Modify: `qun_alpha/notion_writer.py`
- Test: `tests/test_notion_writer.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_notion_writer.py` 末尾**

```python
from qun_alpha.models import Link
from qun_alpha.notion_writer import link_to_properties, write_links


def _link():
    return Link(
        url="https://example.com/42", title="profiling founder 梦琪",
        shared_by=["小李", "老王"], related_companies=["invoko.ai"],
        first_seen=1716700000,
        sources=[SourceRef(group_name="AI投资群", sender="小李",
                           timestamp=1716700000, msg_id="l1")],
    )


def test_link_to_properties_maps_fields():
    props = link_to_properties(_link())
    assert props["Link"]["title"][0]["text"]["content"] == "https://example.com/42"
    assert props["Title"]["rich_text"][0]["text"]["content"] == "profiling founder 梦琪"
    assert {o["name"] for o in props["SharedBy"]["multi_select"]} == {"小李", "老王"}
    assert props["Related"]["multi_select"][0]["name"] == "invoko.ai"


def test_write_links_updates_when_present():
    client = FakeClient(existing_id="oldlink")
    out = write_links([_link()], client=client,
                      database_id="ldb", dry_run=False)
    assert client.updated[0]["page_id"] == "oldlink"
    assert out == ["oldlink"]


def test_write_links_dry_run():
    payloads = write_links([_link()], client=None,
                           database_id="ldb", dry_run=True)
    assert payloads[0]["parent"]["database_id"] == "ldb"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: FAIL，`ImportError: cannot import name 'link_to_properties'`

- [ ] **Step 3: 在 `qun_alpha/notion_writer.py` 顶部 import 增加 Link，并在文件末尾追加：**

把 import 行改为：
```python
from qun_alpha.models import Company, Person, Link
```

文件末尾追加：
```python
def link_to_properties(link: Link) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Link": _title(link.url),
    }
    if link.title:
        props["Title"] = _rt(link.title)
    if link.shared_by:
        props["SharedBy"] = {
            "multi_select": [{"name": s[:100]} for s in link.shared_by]}
    if link.related_companies:
        props["Related"] = {
            "multi_select": [{"name": c[:100]} for c in link.related_companies]}
    return props


def write_links(links: list[Link], client: Any, database_id: str,
                dry_run: bool = False) -> list[Any]:
    return _upsert_all(links, client, database_id, "Link",
                       lambda link: link.url, link_to_properties, dry_run)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/notion_writer.py tests/test_notion_writer.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: notion_writer 写入 Links 表 (upsert)"
```

---

## Task 4: 一次性建库 ensure_databases

**说明**：首次使用时按固定 schema 在父页面下创建三张数据库，返回 id。dry_run 返回 create payload。

**Files:**
- Modify: `qun_alpha/notion_writer.py`
- Test: `tests/test_notion_writer.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_notion_writer.py` 末尾**

```python
from qun_alpha.notion_writer import ensure_databases


class _DbCreator:
    def __init__(self):
        self.created = []
        self._n = 0
    def create(self, **kw):
        self._n += 1
        self.created.append(kw)
        return {"id": f"db{self._n}"}


class CreatorClient:
    def __init__(self):
        self.databases = _DbCreator()


def test_ensure_databases_creates_three():
    client = CreatorClient()
    ids = ensure_databases(client, parent_page_id="page123", dry_run=False)
    assert set(ids.keys()) == {"companies", "people", "links"}
    assert len(client.databases.created) == 3
    # 每张库都挂在父页面下
    assert client.databases.created[0]["parent"]["page_id"] == "page123"
    # Companies 库含 Status select 与 Score number
    comp = next(c for c in client.databases.created
                if "Company" in c["properties"])
    assert "Status" in comp["properties"]
    assert "Score" in comp["properties"]


def test_ensure_databases_dry_run():
    payloads = ensure_databases(None, parent_page_id="page123", dry_run=True)
    assert len(payloads) == 3
    assert all(p["parent"]["page_id"] == "page123" for p in payloads)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: FAIL，`ImportError: cannot import name 'ensure_databases'`

- [ ] **Step 3: 在 `qun_alpha/notion_writer.py` 末尾追加：**

```python
_STATUS_OPTIONS = [{"name": "emerging"}, {"name": "known"},
                   {"name": "noise"}, {"name": "unclear"}]

_COMPANIES_SCHEMA = {
    "Company": {"title": {}},
    "Score": {"number": {}},
    "Mntns": {"number": {}},
    "Status": {"select": {"options": _STATUS_OPTIONS}},
    "Signal": {"rich_text": {}},
    "Confidence": {"number": {}},
    "Sector": {"select": {}},
    "Stage": {"select": {}},
    "Financials": {"rich_text": {}},
    "Investors": {"multi_select": {}},
    "Action": {"select": {}},
}

_PEOPLE_SCHEMA = {
    "Person": {"title": {}},
    "Mntns": {"number": {}},
    "Role": {"rich_text": {}},
    "Affiliated": {"multi_select": {}},
    "Quotes": {"rich_text": {}},
}

_LINKS_SCHEMA = {
    "Link": {"title": {}},
    "Title": {"rich_text": {}},
    "SharedBy": {"multi_select": {}},
    "Related": {"multi_select": {}},
}

_DB_SPECS = [
    ("companies", "Companies", _COMPANIES_SCHEMA),
    ("people", "People", _PEOPLE_SCHEMA),
    ("links", "Links", _LINKS_SCHEMA),
]


def ensure_databases(client: Any, parent_page_id: str, dry_run: bool = False):
    """在父页面下创建 Companies/People/Links 三库。
    dry_run 返回 create payload 列表；实跑返回 {key: database_id}。"""
    if dry_run:
        return [
            {"parent": {"page_id": parent_page_id},
             "title": [{"text": {"content": db_title}}],
             "properties": schema}
            for _, db_title, schema in _DB_SPECS
        ]
    ids: dict[str, str] = {}
    for key, db_title, schema in _DB_SPECS:
        db = client.databases.create(
            parent={"page_id": parent_page_id},
            title=[{"text": {"content": db_title}}],
            properties=schema,
        )
        ids[key] = db["id"]
    return ids
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notion_writer.py -q`
Expected: PASS（12 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/notion_writer.py tests/test_notion_writer.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: notion_writer ensure_databases 一次性建三库"
```

---

## Task 5: cli 接入 People/Links + init-notion 命令

**Files:**
- Modify: `qun_alpha/cli.py`
- Test: `tests/test_cli_smoke.py`

- [ ] **Step 1: 改写 `tests/test_cli_smoke.py`**（整文件替换为下面内容）

```python
import json
from qun_alpha.cli import run_pipeline


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
        {"kind": "person", "name": "老王", "role": "投资人",
         "source": {"group_name": "AI投资群", "sender": "老王",
                    "timestamp": 1716700000, "msg_id": mid}},
    ])


def test_run_pipeline_end_to_end(tmp_path):
    result = run_pipeline(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"],
        start=0, end=2_000_000_000,
        max_messages=1,
        prompt_version="v1",
        runner=_fake_runner,
        cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True,
    )
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["people"] >= 1
    # 三类 payload 各自带对的 database_id
    assert result["company_payloads"][0]["parent"]["database_id"] == "cdb"
    assert result["people_payloads"][0]["parent"]["database_id"] == "pdb"
    assert result["company_payloads"][0]["properties"]["Mntns"]["number"] == 2
    assert result["people_payloads"][0]["properties"]["Person"]["title"][0]["text"]["content"] == "老王"
    assert result["link_payloads"] == []     # 本样本无链接
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_cli_smoke.py -q`
Expected: FAIL（`run_pipeline` 还没有 `people_db_id` 参数，返回 dict 也没有 `company_payloads`/`people_payloads`/`link_payloads`）

- [ ] **Step 3: 改写 `qun_alpha/cli.py`**（整文件替换为下面内容）

```python
from __future__ import annotations
from typing import Any, Callable, Optional
import typer
from qun_alpha import chat_reader, extractor, aggregator, notion_writer
from qun_alpha.config import load_config

app = typer.Typer(help="群聊投资机会分析")


def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 notion_client: Any,
                 companies_db_id: str, people_db_id: str, links_db_id: str,
                 dry_run: bool) -> dict:
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)

    raw: list = []
    for ch in chunks:
        raw.extend(extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir))

    companies, people, links = aggregator.aggregate(raw)
    company_payloads = notion_writer.write_companies(
        companies, client=notion_client, database_id=companies_db_id, dry_run=dry_run)
    people_payloads = notion_writer.write_people(
        people, client=notion_client, database_id=people_db_id, dry_run=dry_run)
    link_payloads = notion_writer.write_links(
        links, client=notion_client, database_id=links_db_id, dry_run=dry_run)

    return {
        "chunks": len(chunks),
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "company_payloads": company_payloads,
        "people_payloads": people_payloads,
        "link_payloads": link_payloads,
    }


def _notion_client(cfg):
    from notion_client import Client
    return Client(auth=cfg.notion_token)


@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒（默认≈2033，等于无上界）"),
    config_path: str = typer.Option("config.json"),
    dry_run: bool = typer.Option(True, help="只预演不写 Notion"),
):
    """分析指定群的指定时间段，输出实体并（可选）写 Notion 三张表。"""
    cfg = load_config(config_path)
    client = None if dry_run else _notion_client(cfg)
    result = run_pipeline(
        export_path=export_path,
        group_ids=[g.strip() for g in groups.split(",") if g.strip()],
        start=start, end=end,
        max_messages=cfg.max_messages_per_chunk,
        prompt_version=cfg.prompt_version,
        runner=extractor.default_claude_runner,
        cache_dir=cfg.cache_dir,
        notion_client=client,
        companies_db_id=cfg.notion_companies_db_id,
        people_db_id=cfg.notion_people_db_id,
        links_db_id=cfg.notion_links_db_id,
        dry_run=dry_run,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")


@app.command("init-notion")
def init_notion(config_path: str = typer.Option("config.json")):
    """在配置的父页面下创建 Companies/People/Links 三张数据库，并打印 database_id。"""
    cfg = load_config(config_path)
    client = _notion_client(cfg)
    ids = notion_writer.ensure_databases(client, parent_page_id=cfg.notion_parent_page_id)
    typer.echo("已创建数据库，请把下面的 id 填进 config.json：")
    for key, db_id in ids.items():
        typer.echo(f"  {key}: {db_id}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_cli_smoke.py -q`
Expected: PASS（1 passed）

- [ ] **Step 5: 跑全套**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（13 个 notion_writer + cli 等，约 29 passed）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/cli.py tests/test_cli_smoke.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: cli 写入 People/Links + init-notion 建库命令"
```

---

## 完成标准（Plan 2a）

- [ ] `pytest -q` 全绿
- [ ] `write_companies/write_people/write_links` 都是 upsert：库里有则 update、无则 create；dry_run 仍只返回 payload
- [ ] `ensure_databases` 能按 schema 建三库
- [ ] `run_pipeline` 同时写三张表并返回三类 payload
- [ ] 新增 `qun-alpha init-notion` 命令

## 后续（不在本计划）

- Plan 2b：orchestrator 状态机 + FastAPI + SSE 进度 + 前端操作台 + cli_launcher（`qun-alpha serve`）。
- Plan 3：decrypt_service 封装 wechat-decrypt + Railway 落地页。
- 真实 `claude -p` 与真实 Notion 的集成测试（手动、不进 CI）。
