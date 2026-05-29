import json
from qun_alpha.cli import run_pipeline


def _fake_runner(prompt):
    import re
    m = re.search(r"msg_id=(\w+)", prompt)
    mid = m.group(1) if m else "m1"
    return json.dumps([
        {"kind": "company", "name": "IrisGo", "quote": "拿了$2.8M种子轮",
         "commentary": "under-the-radar AI seed",
         "source": {"group_name": "AI投资群", "sender": "老王",
                    "timestamp": 1716700000, "msg_id": mid},
         "financials": "$2.8M 种子轮", "investors": ["AI Fund"], "confidence": 0.8},
        {"kind": "person", "name": "老王", "role": "投资人",
         "source": {"group_name": "AI投资群", "sender": "老王",
                    "timestamp": 1716700000, "msg_id": mid}},
    ])


def test_run_pipeline_end_to_end(tmp_path):
    result = run_pipeline(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"],
        start=0, end=2_000_000_000,
        max_messages=1,
        prompt_version="v1",
        runner=_fake_runner,
        cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True,
    )
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["people"] >= 1
    assert result["company_payloads"][0]["parent"]["database_id"] == "cdb"
    assert result["people_payloads"][0]["parent"]["database_id"] == "pdb"
    assert result["company_payloads"][0]["properties"]["Mntns"]["number"] == 2
    assert result["people_payloads"][0]["properties"]["Person"]["title"][0]["text"]["content"] == "老王"
    assert result["link_payloads"] == []
