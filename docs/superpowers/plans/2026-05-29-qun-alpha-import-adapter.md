# 群聊投资机会分析 — 导入适配器 (Plan 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 wechat-decrypt `export_all_chats.py` 的真实导出目录（每会话一个 JSON 文件）转换成本项目 pipeline 吃的单数组格式，并提供 `qun-alpha import-export` 命令。这是连通真实微信数据与本项目管线的桥。

**Architecture:** 新增 `wechat_import.py`：纯函数把单个 wechat-decrypt 会话 JSON 映射成我们的 group 结构，再把整个导出目录合并写出单数组 JSON（`chat_reader.load_export` 直接可读）。零 I/O 之外的依赖，用真实 schema 的 fixture 完整 TDD。

**Tech Stack:** Python 3.10+，typer，pytest。沿用 `~/qun-alpha/.venv`，测试 `.venv/bin/pytest`。

---

## 背景：两种格式

**wechat-decrypt 真实导出**（每会话一个文件，已核对源码 export_all_chats.py:1156-1167 与 export_chat.py:94-110）：
```json
{
  "chat": "AI投资群",
  "username": "12345@chatroom",
  "is_group": true,
  "messages": [
    {"local_id": 1, "timestamp": 1716700000, "sender": "老王", "content": "IrisGo 拿了 $2.8M 种子轮"},
    {"local_id": 2, "timestamp": 1716700100, "sender": "me", "content": "[图片]", "type": "image"}
  ]
}
```
注意：`type` 为 text 时**省略**；无内容时 `content` 省略；自己发的 `sender` 为 `"me"`。

**本项目 pipeline 格式**（`chat_reader.load_export` 读的单数组）：
```json
[{"group_id": "...", "group_name": "...", "messages": [
  {"id": "...", "sender": "...", "timestamp": 0, "type": "text", "text": "..."}]}]
```

映射：`username→group_id`、`chat→group_name`、`local_id→id`、`content→text`(缺省 "")、`type` 缺省 "text"。

## File Structure
```
qun_alpha/
  wechat_import.py     # 新：to_group(单会话dict) + convert_export_dir(src_dir, out_path, groups_only)
  cli.py               # 改：增 import-export 命令
tests/
  fixtures/wechat_export/   # 新：两个真实schema样本（一个群、一个单聊）
  test_wechat_import.py     # 新
```

---

## Task 1: wechat_import 适配器

**Files:**
- Create: `tests/fixtures/wechat_export/group_ai.json`
- Create: `tests/fixtures/wechat_export/dm_friend.json`
- Create: `tests/fixtures/wechat_export/_export_index.json`
- Create: `qun_alpha/wechat_import.py`
- Test: `tests/test_wechat_import.py`

- [ ] **Step 1: 写 fixture（真实 wechat-decrypt schema）**

`tests/fixtures/wechat_export/group_ai.json`:
```json
{
  "chat": "AI投资群",
  "username": "12345@chatroom",
  "is_group": true,
  "messages": [
    {"local_id": 1, "timestamp": 1716700000, "sender": "老王", "content": "IrisGo 拿了 $2.8M 种子轮"},
    {"local_id": 2, "timestamp": 1716700100, "sender": "me", "content": "[图片]", "type": "image"},
    {"local_id": 3, "timestamp": 1716700200, "sender": "小李", "type": "voice"}
  ]
}
```

`tests/fixtures/wechat_export/dm_friend.json`:
```json
{
  "chat": "张三",
  "username": "wxid_zhangsan",
  "messages": [
    {"local_id": 1, "timestamp": 1716700050, "sender": "张三", "content": "你好"}
  ]
}
```

`tests/fixtures/wechat_export/_export_index.json`:
```json
{"note": "这是 wechat-decrypt 的索引文件，应被适配器跳过"}
```

- [ ] **Step 2: 写失败测试 `tests/test_wechat_import.py`**

```python
import json
from qun_alpha.wechat_import import to_group, convert_export_dir

SRC = "tests/fixtures/wechat_export"


def test_to_group_maps_fields():
    raw = {
        "chat": "AI投资群", "username": "12345@chatroom", "is_group": True,
        "messages": [
            {"local_id": 1, "timestamp": 1716700000, "sender": "老王",
             "content": "IrisGo 拿了 $2.8M 种子轮"},
            {"local_id": 3, "timestamp": 1716700200, "sender": "小李", "type": "voice"},
        ],
    }
    g = to_group(raw)
    assert g["group_id"] == "12345@chatroom"
    assert g["group_name"] == "AI投资群"
    m1 = g["messages"][0]
    assert m1["id"] == "1"
    assert m1["text"] == "IrisGo 拿了 $2.8M 种子轮"
    assert m1["type"] == "text"          # content 有、type 省略 → 默认 text
    m2 = g["messages"][1]
    assert m2["type"] == "voice"
    assert m2["text"] == ""              # content 省略 → 空串


def test_convert_export_dir_writes_array(tmp_path):
    out = tmp_path / "all.json"
    n = convert_export_dir(SRC, str(out))
    assert n == 2                         # 群 + 单聊（_export_index.json 被跳过）
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    gids = {g["group_id"] for g in data}
    assert "12345@chatroom" in gids and "wxid_zhangsan" in gids


def test_convert_groups_only(tmp_path):
    out = tmp_path / "groups.json"
    n = convert_export_dir(SRC, str(out), groups_only=True)
    assert n == 1                         # 只保留 is_group 的会话
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["group_id"] == "12345@chatroom"


def test_converted_output_loads_via_chat_reader(tmp_path):
    # 转换结果必须能被现有 chat_reader.load_export 直接消费
    from qun_alpha.chat_reader import load_export
    out = tmp_path / "all.json"
    convert_export_dir(SRC, str(out))
    messages = load_export(str(out))
    assert any(m.text.startswith("IrisGo") for m in messages)
    assert any(m.group_name == "AI投资群" for m in messages)
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/pytest tests/test_wechat_import.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.wechat_import'`

- [ ] **Step 4: 实现 `qun_alpha/wechat_import.py`**

```python
from __future__ import annotations
import json
import os

_INDEX_FILE = "_export_index.json"


def to_group(raw: dict) -> dict:
    """单个 wechat-decrypt 会话 dict → 本项目 group 结构。"""
    messages = []
    for m in raw.get("messages", []):
        messages.append({
            "id": str(m.get("local_id", "")),
            "sender": m.get("sender", ""),
            "timestamp": int(m.get("timestamp", 0)),
            "type": m.get("type", "text"),          # text 时源文件省略
            "text": m.get("content", ""),           # 无内容时源文件省略
        })
    return {
        "group_id": raw.get("username", ""),
        "group_name": raw.get("chat", raw.get("username", "")),
        "messages": messages,
    }


def convert_export_dir(src_dir: str, out_path: str,
                       groups_only: bool = False) -> int:
    """把 wechat-decrypt 导出目录里的每会话 JSON 合并成单数组写到 out_path。
    跳过 _export_index.json。groups_only=True 时只保留 is_group 的会话。
    返回写入的会话数。"""
    groups = []
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".json") or fn == _INDEX_FILE:
            continue
        with open(os.path.join(src_dir, fn), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if groups_only and not raw.get("is_group"):
            continue
        groups.append(to_group(raw))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)
    return len(groups)
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/pytest tests/test_wechat_import.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/wechat_import.py tests/test_wechat_import.py tests/fixtures/wechat_export/
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: wechat_import 适配器 (真实导出目录 → pipeline 单数组)"
```

---

## Task 2: cli import-export 命令

**Files:**
- Modify: `qun_alpha/cli.py`
- Test: `tests/test_wechat_import.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_wechat_import.py` 末尾**

```python
def test_cli_import_export_callable(tmp_path):
    # import_export 是一个可直接调用的薄函数（typer 命令体）
    from qun_alpha.cli import import_export
    out = tmp_path / "out.json"
    n = import_export(src_dir=SRC, out_path=str(out), groups_only=False)
    assert n == 2
    assert out.exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_wechat_import.py::test_cli_import_export_callable -q`
Expected: FAIL，`ImportError: cannot import name 'import_export'`

- [ ] **Step 3: 修改 `qun_alpha/cli.py`**

在文件顶部 import 增加：
```python
from qun_alpha import wechat_import
```

在 `if __name__ == "__main__":` 之前追加：
```python
@app.command("import-export")
def import_export(
    src_dir: str = typer.Option(..., help="wechat-decrypt 导出目录（每会话一个 JSON）"),
    out_path: str = typer.Option("exported_chats/all.json", help="合并输出的单数组 JSON"),
    groups_only: bool = typer.Option(False, help="只导入群聊（跳过单聊）"),
) -> int:
    """把 wechat-decrypt 的导出目录转换成本项目可读的单数组 JSON。"""
    n = wechat_import.convert_export_dir(src_dir, out_path, groups_only=groups_only)
    typer.echo(f"已转换 {n} 个会话 → {out_path}")
    return n
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_wechat_import.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 跑全套**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（约 55 passed：50 + wechat_import 5）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/cli.py tests/test_wechat_import.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: cli import-export 命令"
```

---

## 完成标准（Plan 3a）

- [ ] `pytest -q` 全绿（约 55 passed）
- [ ] `to_group` 正确映射真实 schema（username/chat/local_id/content/type 缺省）
- [ ] `convert_export_dir` 跳过 _export_index.json、支持 groups_only、输出能被 `chat_reader.load_export` 直接消费
- [ ] `qun-alpha import-export` 命令可用

## 后续（不在本计划）

- Plan 3b：decrypt_service 封装 wechat-decrypt 的密钥提取/解库/导出（含 sudo + codesign 重签名的人话引导，需用户在 Mac 上配合执行）+ Railway 静态落地引导页。
- 端到端验收：真机解密 → import-export → serve → 真 `claude -p` + 真 Notion。
