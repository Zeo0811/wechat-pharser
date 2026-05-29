from qun_alpha.doctor import check_all, all_ok, Check


def _which(present):
    return lambda name: ("/usr/bin/" + name) if name in present else None


def test_all_green_when_everything_present():
    checks = check_all(system="Darwin", which=_which({"cc", "git", "claude", "codex"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    assert all_ok(checks)
    assert {c.name for c in checks} >= {"macOS", "Python ≥3.10", "至少一个模型后端"}


def test_non_macos_fails():
    checks = check_all(system="Linux", which=_which({"cc", "git", "claude"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    mac = next(c for c in checks if c.name == "macOS")
    assert mac.ok is False
    assert not all_ok(checks)


def test_missing_xcode_clt_has_fix():
    checks = check_all(system="Darwin", which=_which({"claude"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    clt = next(c for c in checks if "Xcode" in c.name)
    assert clt.ok is False
    assert "xcode-select" in clt.fix


def test_one_backend_enough_individual_nonblocking():
    checks = check_all(system="Darwin", which=_which({"cc", "git", "claude"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    assert all_ok(checks)
    backend = next(c for c in checks if c.name == "至少一个模型后端")
    assert backend.ok is True


def test_no_backend_blocks():
    checks = check_all(system="Darwin", which=_which({"cc", "git"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    assert not all_ok(checks)
    backend = next(c for c in checks if c.name == "至少一个模型后端")
    assert backend.ok is False


def test_python_too_old_blocks():
    checks = check_all(system="Darwin", which=_which({"cc", "git", "claude"}),
                       exists=lambda p: True, py_ge_310=False, home="/h")
    assert not all_ok(checks)
