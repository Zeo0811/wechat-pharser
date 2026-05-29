import json
from qun_alpha.wechat_import import to_group, convert_export_dir

SRC = "tests/fixtures/wechat_export"


def test_to_group_maps_fields():
    raw = {
        "chat": "AI投资群", "username": "12345@chatroom", "is_group": True,
        "messages": [
            {"local_id": 1, "timestamp": 1716700000, "sender": "老王",
             "content": "IrisGo 拿了 $2.8M 种子轮"},
            {"local_id": 3, "timestamp": 1716700200, "sender": "小李", "type": "voice"},
        ],
    }
    g = to_group(raw)
    assert g["group_id"] == "12345@chatroom"
    assert g["group_name"] == "AI投资群"
    m1 = g["messages"][0]
    assert m1["id"] == "1"
    assert m1["text"] == "IrisGo 拿了 $2.8M 种子轮"
    assert m1["type"] == "text"
    m2 = g["messages"][1]
    assert m2["type"] == "voice"
    assert m2["text"] == ""


def test_convert_export_dir_writes_array(tmp_path):
    out = tmp_path / "all.json"
    n = convert_export_dir(SRC, str(out))
    assert n == 2
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    gids = {g["group_id"] for g in data}
    assert "12345@chatroom" in gids and "wxid_zhangsan" in gids


def test_convert_groups_only(tmp_path):
    out = tmp_path / "groups.json"
    n = convert_export_dir(SRC, str(out), groups_only=True)
    assert n == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["group_id"] == "12345@chatroom"


def test_converted_output_loads_via_chat_reader(tmp_path):
    from qun_alpha.chat_reader import load_export
    out = tmp_path / "all.json"
    convert_export_dir(SRC, str(out))
    messages = load_export(str(out))
    assert any(m.text.startswith("IrisGo") for m in messages)
    assert any(m.group_name == "AI投资群" for m in messages)
