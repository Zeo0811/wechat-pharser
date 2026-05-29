import json
import pytest
from qun_alpha.config import load_config, Config


def test_load_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "notion_token": "secret_x",
        "notion_parent_page_id": "page123",
        "max_messages_per_chunk": 50,
    }), encoding="utf-8")
    cfg = load_config(str(p))
    assert isinstance(cfg, Config)
    assert cfg.notion_token == "secret_x"
    assert cfg.max_messages_per_chunk == 50
    assert cfg.prompt_version == "v1"          # 默认值


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.json"))


def test_decrypt_path_defaults(tmp_path):
    import json
    from qun_alpha.config import load_config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.wechat_decrypt_repo.endswith("ylytdeng-wechat-decrypt")
    assert cfg.raw_export_dir == "exported_chats/raw"
    assert cfg.export_path == "exported_chats/all.json"
