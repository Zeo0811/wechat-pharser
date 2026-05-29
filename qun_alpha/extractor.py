from __future__ import annotations
import json
import os
import subprocess
from typing import Callable, Optional
from pydantic import TypeAdapter, ValidationError
from qun_alpha.models import MessageChunk, RawEntity

Runner = Callable[[str], str]
_ADAPTER = TypeAdapter(list[RawEntity])

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
