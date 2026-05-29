# 群聊投资机会分析 — 核心管线 (Plan 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 命令行可运行的核心管线：读取 wechat-decrypt 导出的聊天 JSON → 用本地 Claude Code CLI 逐块抽取实体 → 跨块去重聚合打分 → 写入 Notion 三张关联表。

**Architecture:** 确定性 map-reduce 管线。`extractor` 无状态、模型只读单块吐 JSON；`aggregator` 是纯 Python 函数，负责全部去重/打分/分诊（质量命门，重点 TDD）；`notion_writer` 把聚合结果 upsert 进 Notion。各模块通过 pydantic 数据模型通信，均可独立喂假数据测试。

**Tech Stack:** Python 3.10+，pydantic v2（数据模型 + 校验模型输出），Typer（CLI），notion-client（Notion API），pytest（测试）。模型调用走 `claude -p` headless（subprocess，依赖注入便于 mock）。

---

## File Structure

```
~/qun-alpha/
  pyproject.toml                 # 项目元数据 + 依赖
  qun_alpha/
    __init__.py
    models.py                    # Message / MessageChunk / SourceRef / RawEntity / Company / Person / Link
    chat_reader.py               # 读 wechat-decrypt 导出 JSON → Message[] → 过滤 → 切块 MessageChunk[]
    extractor.py                 # MessageChunk → RawEntity[]，调 claude -p，校验+重试+缓存
    aggregator.py                # RawEntity[] → (Company[], Person[], Link[])，纯函数，去重/打分/分诊
    notion_writer.py             # 实体 → Notion upsert（建库/建页/关联），dry-run 支持
    config.py                    # 读 config.json（notion token、db ids、prompt 版本等）
    cli.py                       # Typer：analyze 命令串起全管线
  tests/
    fixtures/
      export_sample.json         # 一份脱敏的导出样本
      raw_entities_sample.json   # 构造的 RawEntity 列表，喂 aggregator
    test_models.py
    test_chat_reader.py
    test_extractor.py
    test_aggregator.py
    test_notion_writer.py
    test_cli_smoke.py
```

每个文件单一职责；`aggregator.py` 是纯逻辑、零 I/O，最易测也最该测。

---

## Task 0: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `qun_alpha/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: 创建虚拟环境**

```bash
cd ~/qun-alpha
python3 -m venv .venv
source .venv/bin/activate
python --version   # 期望 3.10+
```

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "qun-alpha"
version = "0.1.0"
description = "群聊投资机会分析 — 本地优先投资情报管线"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2,<3",
    "typer>=0.12,<1",
    "notion-client>=2.2,<3",
]

[project.optional-dependencies]
dev = ["pytest>=8,<9"]

[project.scripts]
qun-alpha = "qun_alpha.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["qun_alpha*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: 写 `.gitignore`**

```
.venv/
__pycache__/
*.pyc
config.json
*.db
.qun_cache/
exported_chats/
decrypted/
all_keys.json
```

- [ ] **Step 4: 创建空包文件**

```bash
mkdir -p qun_alpha tests/fixtures
touch qun_alpha/__init__.py tests/__init__.py
```

- [ ] **Step 5: 安装依赖**

```bash
pip install -e ".[dev]"
```
Expected: 安装成功，无报错。

- [ ] **Step 6: 验证 pytest 可运行**

Run: `pytest -q`
Expected: `no tests ran`（0 collected，退出码 5），说明环境就绪。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore qun_alpha/__init__.py tests/__init__.py
git commit -m "chore: 项目脚手架 + 依赖"
```

---

## Task 1: 数据模型 (models.py)

**Files:**
- Create: `qun_alpha/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from qun_alpha.models import (
    Message, MessageChunk, SourceRef, RawEntity, Company, Person, Link,
)


def test_message_roundtrip():
    m = Message(
        msg_id="m1", group_id="g1", group_name="AI投资群",
        sender="老王", timestamp=1716700000, text="IrisGo 拿了 $2.8M 种子轮",
    )
    assert m.msg_type == "text"
    assert m.text.startswith("IrisGo")


def test_rawentity_kind_validated():
    src = SourceRef(group_name="AI投资群", sender="老王",
                    timestamp=1716700000, msg_id="m1")
    e = RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮",
                  commentary="under-the-radar AI seed", source=src,
                  financials="$2.8M 种子轮", investors=["AI Fund"], confidence=0.8)
    assert e.kind == "company"
    assert e.investors == ["AI Fund"]
    with pytest.raises(ValidationError):
        RawEntity(kind="planet", name="x", source=src)


def test_company_defaults():
    c = Company(name="IrisGo", score=72, mentions=1, status="emerging",
                signal="拿了$2.8M种子轮 — under-the-radar AI seed",
                first_seen=1716700000, last_seen=1716700000, confidence=0.8)
    assert c.investors == []
    assert c.related_people == []
    assert c.sources == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.models'`

- [ ] **Step 3: 实现 `qun_alpha/models.py`**

```python
# qun_alpha/models.py
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Status = Literal["emerging", "known", "noise", "unclear"]


class Message(BaseModel):
    msg_id: str
    group_id: str
    group_name: str
    sender: str
    timestamp: int            # epoch seconds
    text: str
    msg_type: str = "text"


class MessageChunk(BaseModel):
    chunk_id: str             # hash(group_id + time_start + time_end + prompt_version)
    group_id: str
    group_name: str
    time_start: int
    time_end: int
    messages: list[Message]


class SourceRef(BaseModel):
    group_name: str
    sender: str
    timestamp: int
    msg_id: str


class RawEntity(BaseModel):
    """extractor 从单块吐出的原始观察，未聚合。"""
    kind: Literal["company", "person", "link"]
    name: str
    quote: str = ""           # 原文引用
    commentary: str = ""      # 模型点评
    source: SourceRef
    # company 相关（可选）
    sector: Optional[str] = None
    stage: Optional[str] = None
    financials: Optional[str] = None
    investors: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    catalyst: Optional[str] = None
    risk: Optional[str] = None
    suggested_action: Optional[str] = None
    confidence: Optional[float] = None
    related_people: list[str] = Field(default_factory=list)
    # person 相关
    role: Optional[str] = None
    affiliated_company: Optional[str] = None
    # link 相关
    url: Optional[str] = None
    title: Optional[str] = None
    related_company: Optional[str] = None


class Company(BaseModel):
    name: str
    score: int                # 0-100
    mentions: int
    status: Status
    signal: str               # 合成：引用 + 点评
    first_seen: int
    last_seen: int
    sector: Optional[str] = None
    stage: Optional[str] = None
    financials: Optional[str] = None
    investors: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    catalyst: Optional[str] = None
    risk: Optional[str] = None
    suggested_action: Optional[str] = None
    confidence: float = 0.0
    related_people: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class Person(BaseModel):
    name: str
    mentions: int
    role: Optional[str] = None
    affiliated_companies: list[str] = Field(default_factory=list)
    notable_quotes: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class Link(BaseModel):
    url: str
    title: Optional[str] = None
    shared_by: list[str] = Field(default_factory=list)
    related_companies: list[str] = Field(default_factory=list)
    first_seen: int = 0
    sources: list[SourceRef] = Field(default_factory=list)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_models.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/models.py tests/test_models.py
git commit -m "feat: 数据模型 (Message/RawEntity/Company/Person/Link)"
```

---

## Task 2: 聊天读取与切块 (chat_reader.py)

**说明**：消费 wechat-decrypt `export_all_chats.py` 导出的 JSON。导出格式为每群一个对象，含 `group_id` / `group_name` / `messages[]`，每条 message 含 `id` / `sender` / `timestamp` / `text` / `type`。本任务用 fixture 模拟该格式，真实对接在 Plan 3。

**Files:**
- Create: `tests/fixtures/export_sample.json`
- Create: `qun_alpha/chat_reader.py`
- Test: `tests/test_chat_reader.py`

- [ ] **Step 1: 写 fixture `tests/fixtures/export_sample.json`**

```json
[
  {
    "group_id": "g1",
    "group_name": "AI投资群",
    "messages": [
      {"id": "m1", "sender": "老王", "timestamp": 1716700000, "type": "text", "text": "IrisGo 拿了 $2.8M 种子轮，吴恩达 AI Fund 领投"},
      {"id": "m2", "sender": "小李", "timestamp": 1716700100, "type": "text", "text": "收到"},
      {"id": "m3", "sender": "小李", "timestamp": 1716700200, "type": "text", "text": "[图片]"},
      {"id": "m4", "sender": "老王", "timestamp": 1716786400, "type": "text", "text": "拾象在 buy old shares，dpsk 有希望"}
    ]
  },
  {
    "group_id": "g2",
    "group_name": "Crypto群",
    "messages": [
      {"id": "n1", "sender": "阿强", "timestamp": 1716700050, "type": "text", "text": "锦秋基金悄悄募了一只新基金，字节做 anchor LP"}
    ]
  }
]
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_chat_reader.py
from qun_alpha.chat_reader import load_export, filter_messages, chunk_messages
from qun_alpha.models import Message

FIX = "tests/fixtures/export_sample.json"


def test_load_export_normalizes():
    msgs = load_export(FIX)
    assert all(isinstance(m, Message) for m in msgs)
    m1 = next(m for m in msgs if m.msg_id == "m1")
    assert m1.group_name == "AI投资群"
    assert m1.sender == "老王"
    assert m1.timestamp == 1716700000


def test_filter_by_group_and_time():
    msgs = load_export(FIX)
    out = filter_messages(msgs, group_ids=["g1"], start=1716700000, end=1716700300)
    ids = {m.msg_id for m in out}
    assert ids == {"m1", "m2", "m3"}        # m4 超出时间窗，n1 属于 g2


def test_filter_drops_noise():
    msgs = load_export(FIX)
    out = filter_messages(msgs, group_ids=["g1"], start=0, end=2_000_000_000,
                          drop_noise=True)
    texts = {m.text for m in out}
    assert "收到" not in texts                # 垃圾过滤
    assert "[图片]" not in texts              # 非文本占位过滤
    assert any("IrisGo" in t for t in texts)


def test_chunk_by_size():
    msgs = load_export(FIX)
    g1 = filter_messages(msgs, group_ids=["g1"], start=0, end=2_000_000_000)
    chunks = chunk_messages(g1, max_messages=2, prompt_version="v1")
    assert len(chunks) == 2                   # 4 条 → 2 块（含 m4）
    assert chunks[0].group_id == "g1"
    assert chunks[0].chunk_id != chunks[1].chunk_id
    assert chunks[0].time_start <= chunks[0].time_end


def test_chunk_ids_stable():
    msgs = load_export(FIX)
    g1 = filter_messages(msgs, group_ids=["g1"], start=0, end=2_000_000_000)
    a = chunk_messages(g1, max_messages=2, prompt_version="v1")
    b = chunk_messages(g1, max_messages=2, prompt_version="v1")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]   # 确定性
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_chat_reader.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.chat_reader'`

- [ ] **Step 4: 实现 `qun_alpha/chat_reader.py`**

```python
# qun_alpha/chat_reader.py
from __future__ import annotations
import json
import hashlib
from qun_alpha.models import Message, MessageChunk

# 纯文字垃圾：精确匹配即丢
_NOISE_EXACT = {"收到", "好的", "ok", "OK", "[图片]", "[表情]", "[语音]",
                "[视频]", "[链接]", "签到", "打卡", "+1", "👍"}


def load_export(path: str) -> list[Message]:
    """读取 wechat-decrypt 导出 JSON，归一化为 Message[]。"""
    with open(path, "r", encoding="utf-8") as f:
        groups = json.load(f)
    out: list[Message] = []
    for g in groups:
        gid = g["group_id"]
        gname = g["group_name"]
        for m in g.get("messages", []):
            out.append(Message(
                msg_id=str(m["id"]),
                group_id=gid,
                group_name=gname,
                sender=m.get("sender", ""),
                timestamp=int(m["timestamp"]),
                text=m.get("text", ""),
                msg_type=m.get("type", "text"),
            ))
    return out


def _is_noise(m: Message) -> bool:
    t = m.text.strip()
    if not t:
        return True
    if t in _NOISE_EXACT:
        return True
    if t.startswith("[") and t.endswith("]"):   # 富媒体占位
        return True
    if len(t) < 4 and not any(ch.isalnum() for ch in t):
        return True
    return False


def filter_messages(messages: list[Message], group_ids: list[str],
                    start: int, end: int, drop_noise: bool = False) -> list[Message]:
    gset = set(group_ids)
    out = [m for m in messages
           if m.group_id in gset and start <= m.timestamp <= end]
    if drop_noise:
        out = [m for m in out if not _is_noise(m)]
    return out


def _chunk_id(group_id: str, t0: int, t1: int, prompt_version: str) -> str:
    raw = f"{group_id}|{t0}|{t1}|{prompt_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def chunk_messages(messages: list[Message], max_messages: int,
                   prompt_version: str) -> list[MessageChunk]:
    """按群分组后，每 max_messages 条切一块。块按 (group, timestamp) 稳定排序。"""
    by_group: dict[str, list[Message]] = {}
    for m in messages:
        by_group.setdefault(m.group_id, []).append(m)

    chunks: list[MessageChunk] = []
    for gid in sorted(by_group):
        msgs = sorted(by_group[gid], key=lambda m: (m.timestamp, m.msg_id))
        gname = msgs[0].group_name if msgs else ""
        for i in range(0, len(msgs), max_messages):
            window = msgs[i:i + max_messages]
            t0 = window[0].timestamp
            t1 = window[-1].timestamp
            chunks.append(MessageChunk(
                chunk_id=_chunk_id(gid, t0, t1, prompt_version),
                group_id=gid,
                group_name=gname,
                time_start=t0,
                time_end=t1,
                messages=window,
            ))
    return chunks
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_chat_reader.py -q`
Expected: PASS（5 passed）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/chat_reader.py tests/test_chat_reader.py tests/fixtures/export_sample.json
git commit -m "feat: chat_reader 读取导出JSON + 过滤 + 切块"
```

---

## Task 3: 实体抽取器 (extractor.py)

**说明**：调本地 `claude -p` headless，对单块吐出 `RawEntity[]` JSON。用依赖注入的 `runner` 便于 mock；模型输出做 pydantic 校验，不合规重试一次后兜底跳过；按 `chunk_id` 缓存到磁盘。

**Files:**
- Create: `qun_alpha/extractor.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_extractor.py
import json
from qun_alpha.models import Message, MessageChunk
from qun_alpha.extractor import extract_chunk, build_prompt

def _chunk():
    return MessageChunk(
        chunk_id="c1", group_id="g1", group_name="AI投资群",
        time_start=1716700000, time_end=1716700100,
        messages=[Message(msg_id="m1", group_id="g1", group_name="AI投资群",
                          sender="老王", timestamp=1716700000,
                          text="IrisGo 拿了 $2.8M 种子轮，AI Fund 领投")],
    )

def test_build_prompt_contains_messages_and_json_instruction():
    p = build_prompt(_chunk())
    assert "IrisGo" in p
    assert "老王" in p
    assert "JSON" in p

def test_extract_parses_valid_json():
    payload = json.dumps([{
        "kind": "company", "name": "IrisGo",
        "quote": "拿了$2.8M种子轮", "commentary": "under-the-radar AI seed",
        "source": {"group_name": "AI投资群", "sender": "老王",
                   "timestamp": 1716700000, "msg_id": "m1"},
        "financials": "$2.8M 种子轮", "investors": ["AI Fund"], "confidence": 0.8
    }])
    fake_runner = lambda prompt: payload
    out = extract_chunk(_chunk(), runner=fake_runner, cache_dir=None)
    assert len(out) == 1
    assert out[0].name == "IrisGo"
    assert out[0].investors == ["AI Fund"]

def test_extract_retries_then_skips_on_bad_json():
    calls = {"n": 0}
    def flaky(prompt):
        calls["n"] += 1
        return "这不是JSON"          # 永远不合规
    out = extract_chunk(_chunk(), runner=flaky, cache_dir=None)
    assert out == []                 # 兜底跳过
    assert calls["n"] == 2           # 调用1 + 重试1

def test_extract_uses_cache(tmp_path):
    payload = json.dumps([{
        "kind": "company", "name": "Cached",
        "source": {"group_name": "AI投资群", "sender": "老王",
                   "timestamp": 1716700000, "msg_id": "m1"}}])
    calls = {"n": 0}
    def once(prompt):
        calls["n"] += 1
        return payload
    c = _chunk()
    a = extract_chunk(c, runner=once, cache_dir=str(tmp_path))
    b = extract_chunk(c, runner=once, cache_dir=str(tmp_path))  # 命中缓存
    assert calls["n"] == 1
    assert a[0].name == b[0].name == "Cached"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_extractor.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.extractor'`

- [ ] **Step 3: 实现 `qun_alpha/extractor.py`**

```python
# qun_alpha/extractor.py
from __future__ import annotations
import json
import os
import subprocess
from typing import Callable, Optional
from pydantic import TypeAdapter, ValidationError
from qun_alpha.models import MessageChunk, RawEntity

Runner = Callable[[str], str]
_ADAPTER = TypeAdapter(list[RawEntity])

PROMPT_VERSION = "v1"

_INSTRUCTION = """你是投资情报分析员。下面是一个微信群某时间段的聊天记录。
请抽取其中提到的【公司/项目】、【人物（创始人/投资人）】、【分享的链接】。
只输出一个 JSON 数组，每个元素形如：
{"kind":"company|person|link","name":"...","quote":"原文引用",
 "commentary":"为何值得关注的简短点评","source":{"group_name":"...","sender":"...","timestamp":<int>,"msg_id":"..."},
 "sector":null,"stage":null,"financials":null,"investors":[],"sentiment":null,
 "catalyst":null,"risk":null,"suggested_action":null,"confidence":0.0,
 "related_people":[],"role":null,"affiliated_company":null,
 "url":null,"title":null,"related_company":null}
没有可抽取内容时输出 []。不要输出 JSON 以外的任何文字。"""


def build_prompt(chunk: MessageChunk) -> str:
    lines = [f"群名：{chunk.group_name}", "聊天记录："]
    for m in chunk.messages:
        lines.append(f"[{m.timestamp}] (msg_id={m.msg_id}) {m.sender}: {m.text}")
    return _INSTRUCTION + "\n\n" + "\n".join(lines)


def default_claude_runner(prompt: str) -> str:
    """调用本地 Claude Code CLI（headless）。"""
    proc = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    return proc.stdout


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def _parse(text: str) -> Optional[list[RawEntity]]:
    try:
        data = json.loads(_strip_fences(text))
        return _ADAPTER.validate_python(data)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return None


def extract_chunk(chunk: MessageChunk, runner: Runner = default_claude_runner,
                  cache_dir: Optional[str] = ".qun_cache") -> list[RawEntity]:
    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{chunk.chunk_id}.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                return _ADAPTER.validate_python(json.load(f))

    prompt = build_prompt(chunk)
    result: Optional[list[RawEntity]] = None
    for _ in range(2):                       # 1 次 + 1 次重试
        parsed = _parse(runner(prompt))
        if parsed is not None:
            result = parsed
            break
    if result is None:
        result = []                          # 兜底跳过

    if cache_path is not None:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump([e.model_dump() for e in result], f, ensure_ascii=False)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_extractor.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/extractor.py tests/test_extractor.py
git commit -m "feat: extractor 调 claude -p 抽取实体 + 校验/重试/缓存"
```

---

## Task 4: 聚合打分 (aggregator.py) — 质量命门

**说明**：纯函数，把 `RawEntity[]` 跨块跨群去重聚合成 `Company[]/Person[]/Link[]`，计算 Mntns、Score、Status、合成 Signal。无 I/O、无模型，全确定性，重点覆盖。

**打分规则（v1 确定性启发式）：**
- `score`（0-100）= 提及次数权重 + 财务信号 + 投资人动向 + 平均置信度 + 点评实质度，clamp 到 0-100。
- `status`：`score < 20` → `noise`；`20 ≤ score < 40` → `unclear`；否则 `emerging`。（`known` 在 v1 不自动判定，留给后续维护已知清单。）

**Files:**
- Create: `qun_alpha/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_aggregator.py
from qun_alpha.models import RawEntity, SourceRef
from qun_alpha.aggregator import aggregate, score_company, normalize_name


def _src(sender="老王", ts=1716700000, mid="m1", group="AI投资群"):
    return SourceRef(group_name=group, sender=sender, timestamp=ts, msg_id=mid)


def test_normalize_name():
    assert normalize_name(" IrisGo ") == "irisgo"
    assert normalize_name("Iris Go") == "irisgo"
    assert normalize_name("锦秋基金") == "锦秋基金"


def test_dedup_companies_across_chunks():
    ents = [
        RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮",
                  commentary="under-the-radar AI seed", source=_src(mid="m1"),
                  financials="$2.8M 种子轮", investors=["AI Fund"], confidence=0.8),
        RawEntity(kind="company", name="iris go", quote="A轮在谈",
                  commentary="持续融资", source=_src(ts=1716786400, mid="m9"),
                  investors=["拾象"], confidence=0.6),
    ]
    companies, people, links = aggregate(ents)
    assert len(companies) == 1
    c = companies[0]
    assert c.name == "IrisGo"               # 保留首个出现的原始写法
    assert c.mentions == 2
    assert set(c.investors) == {"AI Fund", "拾象"}
    assert c.first_seen == 1716700000
    assert c.last_seen == 1716786400
    assert "$2.8M" in c.signal
    assert len(c.sources) == 2


def test_score_rises_with_signal_richness():
    poor = RawEntity(kind="company", name="X", source=_src(), confidence=0.1)
    rich = RawEntity(kind="company", name="Y", quote="2-3亿美金估值",
                     commentary="investors actively tracking paid-acquisition strategy",
                     source=_src(), financials="2-3亿美金", investors=["字节", "拾象"],
                     confidence=0.9)
    assert score_company([rich]) > score_company([poor])


def test_status_noise_for_thin_signal():
    thin = [RawEntity(kind="company", name="路人公司", source=_src(), confidence=0.0)]
    companies, _, _ = aggregate(thin)
    assert companies[0].status == "noise"


def test_status_emerging_for_strong_signal():
    strong = [RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮，AI Fund领投",
                        commentary="exactly the under-the-radar AI seed worth chasing",
                        source=_src(), financials="$2.8M 种子轮",
                        investors=["AI Fund"], confidence=0.85)]
    companies, _, _ = aggregate(strong)
    assert companies[0].status == "emerging"


def test_people_and_links_separated():
    ents = [
        RawEntity(kind="person", name="梦琪", role="创始人",
                  affiliated_company="invoko.ai", quote="一个AI创始人",
                  source=_src(sender="小李", mid="p1")),
        RawEntity(kind="link", name="42章经播客", url="https://example.com/42",
                  title="profiling founder 梦琪", related_company="invoko.ai",
                  source=_src(sender="小李", mid="l1")),
    ]
    companies, people, links = aggregate(ents)
    assert len(companies) == 0
    assert len(people) == 1 and people[0].name == "梦琪"
    assert people[0].affiliated_companies == ["invoko.ai"]
    assert len(links) == 1 and links[0].url == "https://example.com/42"
    assert links[0].related_companies == ["invoko.ai"]


def test_companies_sorted_by_score_desc():
    ents = [
        RawEntity(kind="company", name="Weak", source=_src(mid="a"), confidence=0.1),
        RawEntity(kind="company", name="Strong", quote="$10M ARR",
                  commentary="specific revenue milestone worth chasing",
                  source=_src(mid="b"), financials="$10M ARR",
                  investors=["拾象"], confidence=0.9),
    ]
    companies, _, _ = aggregate(ents)
    assert [c.name for c in companies] == ["Strong", "Weak"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_aggregator.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.aggregator'`

- [ ] **Step 3: 实现 `qun_alpha/aggregator.py`**

```python
# qun_alpha/aggregator.py
from __future__ import annotations
import re
from qun_alpha.models import RawEntity, Company, Person, Link, Status

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    return _WS.sub("", name.strip().lower())


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def score_company(group: list[RawEntity]) -> int:
    """0-100 启发式打分。"""
    mentions = len(group)
    confidences = [e.confidence for e in group if e.confidence is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    has_fin = any(e.financials for e in group)
    investors = _dedup_keep_order([i for e in group for i in e.investors])
    commentary_len = max((len(e.commentary) for e in group), default=0)

    score = 0.0
    score += min(mentions, 5) * 8          # 提及次数，封顶 40
    score += avg_conf * 25                 # 置信度，最高 25
    score += 15 if has_fin else 0          # 有财务信号
    score += min(len(investors), 2) * 6    # 投资人动向，封顶 12
    score += min(commentary_len, 80) / 80 * 8   # 点评实质度，最高 8
    return max(0, min(100, round(score)))


def _status_from_score(score: int) -> Status:
    if score < 20:
        return "noise"
    if score < 40:
        return "unclear"
    return "emerging"


def _build_signal(group: list[RawEntity]) -> str:
    parts = []
    for e in group:
        seg = e.quote.strip()
        if e.commentary.strip():
            seg = f"{seg} — {e.commentary.strip()}" if seg else e.commentary.strip()
        if seg:
            parts.append(seg)
    return " | ".join(_dedup_keep_order(parts))


def _first(values):
    for v in values:
        if v:
            return v
    return None


def aggregate(entities: list[RawEntity]):
    companies_raw: dict[str, list[RawEntity]] = {}
    people_raw: dict[str, list[RawEntity]] = {}
    links_raw: dict[str, list[RawEntity]] = {}

    for e in entities:
        if e.kind == "company":
            companies_raw.setdefault(normalize_name(e.name), []).append(e)
        elif e.kind == "person":
            people_raw.setdefault(normalize_name(e.name), []).append(e)
        elif e.kind == "link":
            key = (e.url or e.name).strip().lower()
            links_raw.setdefault(key, []).append(e)

    companies = [_make_company(g) for g in companies_raw.values()]
    companies.sort(key=lambda c: c.score, reverse=True)
    people = [_make_person(g) for g in people_raw.values()]
    links = [_make_link(g) for g in links_raw.values()]
    return companies, people, links


def _make_company(group: list[RawEntity]) -> Company:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    score = score_company(group_sorted)
    confidences = [e.confidence for e in group_sorted if e.confidence is not None]
    return Company(
        name=group_sorted[0].name,
        score=score,
        mentions=len(group_sorted),
        status=_status_from_score(score),
        signal=_build_signal(group_sorted),
        first_seen=group_sorted[0].source.timestamp,
        last_seen=group_sorted[-1].source.timestamp,
        sector=_first(e.sector for e in group_sorted),
        stage=_first(e.stage for e in group_sorted),
        financials=_first(e.financials for e in group_sorted),
        investors=_dedup_keep_order([i for e in group_sorted for i in e.investors]),
        sentiment=_first(e.sentiment for e in group_sorted),
        catalyst=_first(e.catalyst for e in group_sorted),
        risk=_first(e.risk for e in group_sorted),
        suggested_action=_first(e.suggested_action for e in group_sorted),
        confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        related_people=_dedup_keep_order(
            [p for e in group_sorted for p in e.related_people]),
        sources=[e.source for e in group_sorted],
    )


def _make_person(group: list[RawEntity]) -> Person:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    return Person(
        name=group_sorted[0].name,
        mentions=len(group_sorted),
        role=_first(e.role for e in group_sorted),
        affiliated_companies=_dedup_keep_order(
            [e.affiliated_company for e in group_sorted if e.affiliated_company]),
        notable_quotes=_dedup_keep_order(
            [e.quote for e in group_sorted if e.quote]),
        sources=[e.source for e in group_sorted],
    )


def _make_link(group: list[RawEntity]) -> Link:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    return Link(
        url=group_sorted[0].url or group_sorted[0].name,
        title=_first(e.title for e in group_sorted),
        shared_by=_dedup_keep_order([e.source.sender for e in group_sorted]),
        related_companies=_dedup_keep_order(
            [e.related_company for e in group_sorted if e.related_company]),
        first_seen=group_sorted[0].source.timestamp,
        sources=[e.source for e in group_sorted],
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_aggregator.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/aggregator.py tests/test_aggregator.py
git commit -m "feat: aggregator 去重/打分/分诊/Signal合成 (纯函数)"
```

---

## Task 5: 配置加载 (config.py)

**Files:**
- Create: `qun_alpha/config.py`
- Create: `config.example.json`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
import json
import pytest
from qun_alpha.config import load_config, Config


def test_load_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "notion_token": "secret_x",
        "notion_parent_page_id": "page123",
        "max_messages_per_chunk": 50,
    }), encoding="utf-8")
    cfg = load_config(str(p))
    assert isinstance(cfg, Config)
    assert cfg.notion_token == "secret_x"
    assert cfg.max_messages_per_chunk == 50
    assert cfg.prompt_version == "v1"          # 默认值


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.json"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_config.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.config'`

- [ ] **Step 3: 实现 `qun_alpha/config.py`**

```python
# qun_alpha/config.py
from __future__ import annotations
import json
import os
from pydantic import BaseModel


class Config(BaseModel):
    notion_token: str = ""
    notion_parent_page_id: str = ""
    notion_companies_db_id: str = ""
    notion_people_db_id: str = ""
    notion_links_db_id: str = ""
    max_messages_per_chunk: int = 100
    prompt_version: str = "v1"
    cache_dir: str = ".qun_cache"


def load_config(path: str = "config.json") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在：{path}（可复制 config.example.json）")
    with open(path, "r", encoding="utf-8") as f:
        return Config(**json.load(f))
```

- [ ] **Step 4: 写 `config.example.json`**

```json
{
    "notion_token": "secret_xxx",
    "notion_parent_page_id": "在此填入用于创建数据库的父页面 ID",
    "notion_companies_db_id": "",
    "notion_people_db_id": "",
    "notion_links_db_id": "",
    "max_messages_per_chunk": 100,
    "prompt_version": "v1",
    "cache_dir": ".qun_cache"
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_config.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/config.py config.example.json tests/test_config.py
git commit -m "feat: config 加载器"
```

---

## Task 6: Notion 写入 (notion_writer.py)

**说明**：把聚合结果写进 Notion。v1 先实现 Companies 表的 upsert（按 name 去重：先查后建/更新）。注入 `client`（notion-client 实例）便于 mock；`dry_run=True` 时只返回将写入的 payload、不调 API。People/Links 同构，本任务先做 Companies + dry-run，People/Links 在 Plan 2 补（写库逻辑同型）。

**Files:**
- Create: `qun_alpha/notion_writer.py`
- Test: `tests/test_notion_writer.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_notion_writer.py
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
    payloads = write_companies([_company()], client=BoomClient(),
                               database_id="db1", dry_run=True)
    assert len(payloads) == 1
    assert payloads[0]["parent"]["database_id"] == "db1"


def test_write_companies_calls_create():
    created = []
    class FakeClient:
        class pages:
            @staticmethod
            def create(**kw):
                created.append(kw)
                return {"id": "newpage"}
    out = write_companies([_company()], client=FakeClient(),
                          database_id="db1", dry_run=False)
    assert len(created) == 1
    assert created[0]["parent"]["database_id"] == "db1"
    assert out == ["newpage"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_notion_writer.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.notion_writer'`

- [ ] **Step 3: 实现 `qun_alpha/notion_writer.py`**

```python
# qun_alpha/notion_writer.py
from __future__ import annotations
from typing import Any, Optional
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


def write_companies(companies: list[Company], client: Any, database_id: str,
                    dry_run: bool = False) -> list[Any]:
    results = []
    for c in companies:
        payload = {
            "parent": {"database_id": database_id},
            "properties": company_to_properties(c),
        }
        if dry_run:
            results.append(payload)
            continue
        page = client.pages.create(**payload)
        results.append(page["id"])
    return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_notion_writer.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/notion_writer.py tests/test_notion_writer.py
git commit -m "feat: notion_writer Companies 表 upsert + dry-run"
```

---

## Task 7: CLI 串联全管线 (cli.py)

**说明**：`analyze` 命令把 5 段串起来：load_export → filter → chunk → extract（每块）→ aggregate → write_companies(dry_run)。本任务用 fake runner + dry-run 做端到端冒烟，不碰真模型/真 Notion。

**Files:**
- Create: `qun_alpha/cli.py`
- Test: `tests/test_cli_smoke.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_smoke.py
import json
from qun_alpha.cli import run_pipeline


def _fake_runner(prompt):
    # 任何块都吐一个固定公司，msg_id 从 prompt 里抓第一个
    import re
    m = re.search(r"msg_id=(\w+)", prompt)
    mid = m.group(1) if m else "m1"
    return json.dumps([{
        "kind": "company", "name": "IrisGo", "quote": "拿了$2.8M种子轮",
        "commentary": "under-the-radar AI seed",
        "source": {"group_name": "AI投资群", "sender": "老王",
                   "timestamp": 1716700000, "msg_id": mid},
        "financials": "$2.8M 种子轮", "investors": ["AI Fund"], "confidence": 0.8,
    }])


def test_run_pipeline_end_to_end(tmp_path):
    result = run_pipeline(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"],
        start=0, end=2_000_000_000,
        max_messages=1,                        # 过滤噪声后 g1 剩 m1/m4 两条 → 2 块
        prompt_version="v1",
        runner=_fake_runner,
        cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="db1",
        dry_run=True,
    )
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["notion_payloads"][0]["parent"]["database_id"] == "db1"
    # IrisGo 在两块里各出现一次 → 聚合后 mentions==2
    payload = result["notion_payloads"][0]
    assert payload["properties"]["Company"]["title"][0]["text"]["content"] == "IrisGo"
    assert payload["properties"]["Mntns"]["number"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cli_smoke.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.cli'`

- [ ] **Step 3: 实现 `qun_alpha/cli.py`**

```python
# qun_alpha/cli.py
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
                 notion_client: Any, companies_db_id: str,
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
    payloads = notion_writer.write_companies(
        companies, client=notion_client, database_id=companies_db_id, dry_run=dry_run)

    return {
        "chunks": len(chunks),
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "notion_payloads": payloads,
    }


@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒"),
    config_path: str = typer.Option("config.json"),
    dry_run: bool = typer.Option(True, help="只预演不写 Notion"),
):
    """分析指定群的指定时间段，输出实体并（可选）写 Notion。"""
    cfg = load_config(config_path)
    client = None
    if not dry_run:
        from notion_client import Client
        client = Client(auth=cfg.notion_token)

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
        dry_run=dry_run,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_cli_smoke.py -q`
Expected: PASS（1 passed）

- [ ] **Step 5: 跑全量测试**

Run: `pytest -q`
Expected: 全部 PASS（25 passed：models 3 + chat_reader 5 + extractor 4 + aggregator 7 + config 2 + notion_writer 3 + cli 1）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/cli.py tests/test_cli_smoke.py
git commit -m "feat: cli analyze 串联全管线 + 端到端冒烟测试"
```

---

## 完成标准（Plan 1）

- [ ] `pytest -q` 全绿
- [ ] `aggregator` 的去重/打分/分诊/Signal 合成有完整测试覆盖
- [ ] `qun-alpha analyze --export-path tests/fixtures/export_sample.json --groups g1 --dry-run` 能跑出实体统计（需先 `cp config.example.json config.json` 并填占位）
- [ ] 各模块均可独立喂假数据测试，无对真模型/真 Notion 的硬依赖

## 后续（不在本计划）

- Plan 2：orchestrator 状态机 + FastAPI + SSE 进度 + 前端操作台；notion_writer 补 People/Links + 真正 upsert（先查后更）；真实 `claude -p` 集成测试。
- Plan 3：decrypt_service 封装 wechat-decrypt（密钥提取/解库/导出 JSON，含 sudo/重签名人话引导）+ Railway 静态落地引导页。
