import subprocess
from pathlib import Path

SH = Path("install/install.sh")


def test_install_sh_syntax_ok():
    r = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_install_sh_has_key_steps():
    t = SH.read_text(encoding="utf-8")
    for kw in ["Darwin", "xcode-select", "git clone", "venv",
               "find_keys_codec", "claude", "codex", "qun-alpha doctor",
               "QUN_ALPHA_HOME", ".local/bin"]:
        assert kw in t, f"缺少关键步骤: {kw}"
