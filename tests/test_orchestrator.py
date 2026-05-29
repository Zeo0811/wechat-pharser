import json
from qun_alpha.orchestrator import run_job, ProgressEvent


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
    ])


def _run(tmp_path):
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
    )
    return events, result


def test_run_job_returns_same_shape_as_pipeline(tmp_path):
    events, result = _run(tmp_path)
    assert result["chunks"] == 2
    assert result["companies"] >= 1
    assert result["company_payloads"][0]["parent"]["database_id"] == "cdb"
    assert set(result.keys()) >= {
        "chunks", "raw_entities", "companies", "people", "links",
        "company_payloads", "people_payloads", "link_payloads"}


def test_run_job_emits_progress_stages(tmp_path):
    events, _ = _run(tmp_path)
    assert all(isinstance(e, ProgressEvent) for e in events)
    stages = [e.stage for e in events]
    assert stages[0] == "read"
    assert stages[-1] == "done"
    assert "extract" in stages
    assert "aggregate" in stages
    assert "write" in stages
    assert stages.count("extract") == 2
    assert events[-1].current == events[-1].total


from qun_alpha.job_store import JobStore


def test_run_job_records_progress_to_store(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    store.create("jx", {})
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
        concurrency=3, job_store=store, job_id="jx",
    )
    assert result["chunks"] == 2
    rec = store.load("jx")
    assert len(rec["done"]) == 2
    assert rec["failed"] == []
    assert [e.stage for e in events].count("extract") == 2


from qun_alpha.cursor_store import CursorStore


def test_incremental_skips_old_and_advances_cursor(tmp_path):
    cur = CursorStore(path=str(tmp_path / "cursors.json"))
    cur.set("g1", 1716700000)        # m1(=1716700000) 及更早被跳过；m4(1716786400) 保留
    events = []
    result = run_job(
        export_path="tests/fixtures/export_sample.json",
        group_ids=["g1"], start=0, end=2_000_000_000,
        max_messages=1, prompt_version="v1",
        runner=_fake_runner, cache_dir=str(tmp_path / "cache"),
        notion_client=None,
        companies_db_id="cdb", people_db_id="pdb", links_db_id="ldb",
        dry_run=True, emit=events.append,
        incremental=True, cursor_store=cur,
    )
    assert result["chunks"] == 1                 # 只剩 m4 一块
    assert cur.get("g1") == 1716786400           # 游标推进到本次最大 ts
