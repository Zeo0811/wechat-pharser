from qun_alpha.job_store import JobStore


def test_create_load_list(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("job1", {"export_path": "x.json", "group_ids": ["g1"]})
    rec = s.load("job1")
    assert rec["status"] == "running"
    assert rec["params"]["group_ids"] == ["g1"]
    assert rec["done"] == [] and rec["failed"] == []
    assert [r["job_id"] for r in s.list()] == ["job1"]


def test_mark_done_failed_dedup(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("j", {})
    s.mark_done("j", "c1")
    s.mark_done("j", "c1")
    s.mark_done("j", "c2")
    s.mark_failed("j", "c3")
    rec = s.load("j")
    assert rec["done"] == ["c1", "c2"]
    assert rec["failed"] == ["c3"]


def test_set_status_and_result(tmp_path):
    s = JobStore(dir=str(tmp_path))
    s.create("j", {})
    s.set_status("j", "done", result={"companies": 3})
    rec = s.load("j")
    assert rec["status"] == "done"
    assert rec["result"]["companies"] == 3


def test_load_missing_returns_none(tmp_path):
    assert JobStore(dir=str(tmp_path)).load("nope") is None
