from qun_alpha.decrypt_service import macos_steps, classify_error


def test_macos_steps_sequence():
    steps = macos_steps(repo_dir="/repo/wechat-decrypt", output_dir="/out/chats")
    cmds = [s["command"] for s in steps]
    joined = "\n".join(cmds)
    assert any("killall WeChat" in c for c in cmds)
    idx_sign = next(i for i, c in enumerate(cmds) if "codesign" in c)
    idx_scan = next(i for i, c in enumerate(cmds) if "find_all_keys_macos" in c and "sudo ./" in c)
    idx_decrypt = next(i for i, c in enumerate(cmds) if "decrypt_db.py" in c)
    idx_export = next(i for i, c in enumerate(cmds) if "export_all_chats.py" in c)
    assert idx_sign < idx_scan < idx_decrypt < idx_export
    assert "/repo/wechat-decrypt" in joined
    assert "/out/chats" in joined
    assert all(s["desc"] for s in steps)
    assert any("import-export" in c for c in cmds)


def test_classify_error_known_patterns():
    assert "微信" in classify_error("could not find process 'WeChat'")
    assert "重签名" in classify_error("task_for_pid failed (5): not permitted")
    assert "sudo" in classify_error("Operation not permitted")
    assert "Xcode" in classify_error("cc: command not found")


def test_classify_error_unknown_passthrough():
    msg = classify_error("某种没见过的错误 xyz")
    assert "xyz" in msg
