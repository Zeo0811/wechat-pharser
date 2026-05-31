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
    import os
    result = run_pipeline(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"],
        start=0, end=2_000_000_000,
        max_messages=1,
        prompt_version="v1",
        runner=_fake_runner,
        cache_dir=str(tmp_path / "cache"),
        report_dir=str(tmp_path / "reports"),
    )
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["people"] >= 1
    assert os.path.exists(result["report_md"])
    assert os.path.exists(result["report_docx"])
    assert "company_payloads" not in result
