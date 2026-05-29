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


def _chunk_id(group_id: str, t0: int, t1: int, first_msg_id: str,
              prompt_version: str) -> str:
    # 含窗口首条 msg_id：同群同一秒的多条消息切成单条块时也不会撞缓存
    raw = f"{group_id}|{t0}|{t1}|{first_msg_id}|{prompt_version}"
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
                chunk_id=_chunk_id(gid, t0, t1, window[0].msg_id, prompt_version),
                group_id=gid,
                group_name=gname,
                time_start=t0,
                time_end=t1,
                messages=window,
            ))
    return chunks


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
