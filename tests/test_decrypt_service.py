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


def test_cli_decrypt_guide_returns_steps():
    from qun_alpha.cli import decrypt_guide
    steps = decrypt_guide(repo_dir="/repo/wd", output_dir="/out")
    assert isinstance(steps, list)
    assert len(steps) >= 6
    assert all("command" in s and "desc" in s for s in steps)


from qun_alpha.decrypt_service import (
    admin_applescript, codesign_steps, decrypt_export_steps, run_sequence,
)


def test_admin_applescript_wraps_and_escapes():
    s = admin_applescript('codesign --sign - "/Applications/WeChat.app"')
    assert "with administrator privileges" in s
    assert s.startswith("do shell script ")
    assert '\\"' in s


def test_codesign_steps_sequence():
    steps = codesign_steps()
    assert [s["desc"] for s in steps]
    assert any("killall WeChat" in " ".join(s["argv"]) for s in steps)
    assert any("administrator privileges" in " ".join(s["argv"]) for s in steps)


def test_decrypt_export_steps_paths_and_order():
    steps = decrypt_export_steps(repo_dir="/R", raw_out="/O", export_path="/E.json")
    joined = ["".join(s["argv"]) for s in steps]
    blob = "\n".join(joined)
    assert "/R/find_all_keys_macos.c" in blob
    assert "administrator privileges" in blob
    assert "decrypt_db.py" in blob
    assert "export_all_chats.py /O" in blob
    assert "import-export" in blob and "/E.json" in blob
    idx = lambda kw: next(i for i, b in enumerate(joined) if kw in b)
    assert idx("find_all_keys_macos.c") < idx("administrator privileges") \
           < idx("decrypt_db.py") < idx("export_all_chats.py") < idx("import-export")


def test_run_sequence_runs_all_and_emits():
    events = []
    calls = []
    runner = lambda argv: (calls.append(argv) or (0, ""))
    steps = [{"desc": "a", "argv": ["x"]}, {"desc": "b", "argv": ["y"]}]
    out = run_sequence(steps, runner=runner, emit=events.append)
    assert out["steps"] == 2
    assert len(calls) == 2
    assert [e["current"] for e in events] == [1, 2]
    assert events[0]["total"] == 2 and events[0]["message"] == "a"


def test_run_sequence_stops_on_failure_with_hint():
    import pytest
    calls = []

    def runner(argv):
        calls.append(argv)
        return (1, "task_for_pid failed (5)")

    steps = [{"desc": "scan", "argv": ["s"]}, {"desc": "next", "argv": ["n"]}]
    with pytest.raises(RuntimeError) as ei:
        run_sequence(steps, runner=runner, emit=lambda e: None)
    assert "重签名" in str(ei.value)
    assert len(calls) == 1
