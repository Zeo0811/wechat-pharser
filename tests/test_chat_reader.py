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


def test_chunk_ids_distinct_on_same_timestamp():
    # 同群、同一秒的两条消息，单条切块时 chunk_id 必须不同（否则缓存互撞）
    same_ts = [
        Message(msg_id="x1", group_id="g1", group_name="群", sender="a",
                timestamp=1716700000, text="第一条有内容的消息"),
        Message(msg_id="x2", group_id="g1", group_name="群", sender="b",
                timestamp=1716700000, text="第二条不同内容的消息"),
    ]
    chunks = chunk_messages(same_ts, max_messages=1, prompt_version="v1")
    assert len(chunks) == 2
    assert chunks[0].chunk_id != chunks[1].chunk_id
