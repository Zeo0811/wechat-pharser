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
            "type": m.get("type", "text"),
            "text": m.get("content", ""),
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
