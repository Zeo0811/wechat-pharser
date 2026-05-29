import json
from qun_alpha.cli import model_status


def test_model_status_shows_available_and_current(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude", "codex"])
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_backend": "codex"}), encoding="utf-8")
    info = model_status(config_path=str(p))
    assert info["available"] == ["claude", "codex"]
    assert info["current"] == "codex"


def test_model_status_set_writes_config(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude"])
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_backend": "claude"}), encoding="utf-8")
    info = model_status(config_path=str(p), set_backend="codex")
    assert info["current"] == "codex"
    assert json.loads(p.read_text())["model_backend"] == "codex"


def test_model_status_default_when_no_config(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: [])
    info = model_status(config_path=str(tmp_path / "nope.json"))
    assert info["current"] == "claude"


def test_model_status_rejects_unknown(tmp_path, monkeypatch):
    import pytest
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude"])
    with pytest.raises(ValueError):
        model_status(config_path=str(tmp_path / "c.json"), set_backend="gpt99")
