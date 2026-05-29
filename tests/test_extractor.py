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
