from __future__ import annotations
import shutil
import subprocess
from typing import Callable

BACKENDS = ["claude", "codex"]


def _run(argv: list[str]) -> str:
    """默认执行器：跑 CLI，返回 stdout。"""
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return proc.stdout or ""


def claude_runner(prompt: str, run: Callable[[list], str] = _run) -> str:
    return run(["claude", "-p", prompt])


def codex_runner(prompt: str, run: Callable[[list], str] = _run) -> str:
    return run(["codex", "exec", prompt])


def get_runner(backend: str) -> Callable[[str], str]:
    if backend == "claude":
        return claude_runner
    if backend == "codex":
        return codex_runner
    raise ValueError(f"未知模型后端：{backend}（支持 {BACKENDS}）")


def detect_available() -> list[str]:
    """返回当前 PATH 上可用的后端 CLI。"""
    return [b for b in BACKENDS if shutil.which(b)]
