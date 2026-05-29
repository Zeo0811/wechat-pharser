from __future__ import annotations
import os
from qun_alpha import chat_reader

# 粗估常量（可按需调）
AVG_TOKENS_PER_CHUNK = 7500
USD_PER_CHUNK = 0.02
SECONDS_PER_CHUNK = 8


def estimate_run(*, export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str, cache_dir: str) -> dict:
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)

    cached = 0
    for ch in chunks:
        if cache_dir and os.path.exists(os.path.join(cache_dir, f"{ch.chunk_id}.json")):
            cached += 1
    to_run = len(chunks) - cached
    return {
        "chunks": len(chunks),
        "cached": cached,
        "to_run": to_run,
        "est_tokens": to_run * AVG_TOKENS_PER_CHUNK,
        "est_cost_usd": round(to_run * USD_PER_CHUNK, 2),
        "est_minutes": round(to_run * SECONDS_PER_CHUNK / 60, 1),
    }
