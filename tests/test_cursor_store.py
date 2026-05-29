from qun_alpha.cursor_store import CursorStore


def test_default_zero(tmp_path):
    s = CursorStore(path=str(tmp_path / "cursors.json"))
    assert s.get("g1") == 0


def test_set_get_persist(tmp_path):
    p = str(tmp_path / "cursors.json")
    s = CursorStore(path=p)
    s.set("g1", 1716700000)
    assert s.get("g1") == 1716700000
    assert CursorStore(path=p).get("g1") == 1716700000


def test_set_only_advances(tmp_path):
    s = CursorStore(path=str(tmp_path / "cursors.json"))
    s.set("g1", 100)
    s.set("g1", 50)
    assert s.get("g1") == 100
    s.set("g1", 200)
    assert s.get("g1") == 200
