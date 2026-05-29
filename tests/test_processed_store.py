from qun_alpha.processed_store import ProcessedStore


def test_mark_and_get(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    assert s.get("g1") is None
    s.mark(["g1", "g2"], when="2026-05-29T10:00:00")
    assert s.get("g1") == {"runs": 1, "last": "2026-05-29T10:00:00"}
    assert s.get("g2")["runs"] == 1


def test_mark_increments_runs(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    s.mark(["g1"], when="t1")
    s.mark(["g1"], when="t2")
    assert s.get("g1") == {"runs": 2, "last": "t2"}


def test_multi_instance_same_file(tmp_path):
    p = str(tmp_path / "p.json")
    ProcessedStore(path=p).mark(["g1"], when="t1")
    assert ProcessedStore(path=p).get("g1")["runs"] == 1


def test_all_and_empty_groups(tmp_path):
    s = ProcessedStore(path=str(tmp_path / "p.json"))
    s.mark([], when="t1")
    assert s.all() == {}
    s.mark(["g1"], when="t1")
    assert "g1" in s.all()
