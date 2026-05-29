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
