import os
import json
from qun_alpha.estimate import estimate_run

FIX = "tests/fixtures/export_sample.json"


def test_estimate_counts_chunks(tmp_path):
    est = estimate_run(export_path=FIX, group_ids=["g1"], start=0, end=2_000_000_000,
                       max_messages=1, prompt_version="v1", cache_dir=str(tmp_path))
    assert est["chunks"] == 2
    assert est["cached"] == 0
    assert est["to_run"] == 2
    assert est["est_tokens"] > 0
    assert est["est_cost_usd"] >= 0
    assert est["est_minutes"] >= 0


def test_estimate_counts_cache_hits(tmp_path):
    from qun_alpha import chat_reader
    msgs = chat_reader.load_export(FIX)
    g1 = chat_reader.filter_messages(msgs, group_ids=["g1"], start=0,
                                     end=2_000_000_000, drop_noise=True)
    chunks = chat_reader.chunk_messages(g1, max_messages=1, prompt_version="v1")
    os.makedirs(tmp_path, exist_ok=True)
    with open(os.path.join(str(tmp_path), f"{chunks[0].chunk_id}.json"), "w") as f:
        json.dump([], f)
    est = estimate_run(export_path=FIX, group_ids=["g1"], start=0, end=2_000_000_000,
                       max_messages=1, prompt_version="v1", cache_dir=str(tmp_path))
    assert est["chunks"] == 2
    assert est["cached"] == 1
    assert est["to_run"] == 1
