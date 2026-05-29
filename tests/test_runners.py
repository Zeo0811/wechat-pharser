import pytest
from qun_alpha import runners


def test_claude_runner_builds_cmd():
    calls = []
    out = runners.claude_runner("PROMPT", run=lambda argv: calls.append(argv) or "OUT")
    assert calls[0] == ["claude", "-p", "PROMPT"]
    assert out == "OUT"


def test_codex_runner_builds_cmd():
    calls = []
    out = runners.codex_runner("PROMPT", run=lambda argv: calls.append(argv) or "OUT")
    assert calls[0] == ["codex", "exec", "PROMPT"]
    assert out == "OUT"


def test_get_runner_routes():
    assert runners.get_runner("claude") is runners.claude_runner
    assert runners.get_runner("codex") is runners.codex_runner
    with pytest.raises(ValueError):
        runners.get_runner("gpt99")


def test_detect_available(monkeypatch):
    monkeypatch.setattr(runners.shutil, "which",
                        lambda b: "/usr/bin/" + b if b == "codex" else None)
    assert runners.detect_available() == ["codex"]


def test_get_runner_callable_with_prompt_only():
    # get_runner 返回的函数能只用 (prompt) 调用；用 run= 注入验证不真跑 CLI
    r = runners.get_runner("claude")
    assert r("hi", run=lambda argv: "X") == "X"


def test_ensure_available_raises_when_missing(monkeypatch):
    import pytest
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude"])
    runners.ensure_available("claude")           # 在 → 不抛
    with pytest.raises(RuntimeError):
        runners.ensure_available("codex")        # 不在 → 抛人话错误
