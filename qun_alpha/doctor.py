from __future__ import annotations
import os
import shutil
import sys
import platform
from dataclasses import dataclass
from typing import Callable, Optional

QUN_HOME = os.path.expanduser(os.environ.get("QUN_ALPHA_HOME", "~/.qun-alpha"))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    blocking: bool = True


def check_all(*, system: Optional[str] = None,
              which: Callable[[str], Optional[str]] = shutil.which,
              exists: Callable[[str], bool] = os.path.exists,
              py_ge_310: Optional[bool] = None,
              home: str = QUN_HOME) -> list[Check]:
    sysname = system if system is not None else platform.system()
    pyok = py_ge_310 if py_ge_310 is not None else sys.version_info >= (3, 10)
    cc, git = which("cc"), which("git")
    claude, codex = which("claude"), which("codex")
    checks = [
        Check("macOS", sysname == "Darwin", sysname, "本工具目前仅支持 macOS"),
        Check("Xcode 命令行工具", bool(cc and git), f"cc={cc} git={git}",
              "运行：xcode-select --install"),
        Check("Python ≥3.10", bool(pyok),
              f"{sys.version_info.major}.{sys.version_info.minor}",
              "brew install python@3.12"),
        Check("qun-alpha 安装目录", exists(home), home, "重跑安装器"),
        Check("wechat-decrypt", exists(os.path.join(home, "vendor", "wechat-decrypt")),
              os.path.join(home, "vendor", "wechat-decrypt"), "重跑安装器"),
        Check("claude CLI", bool(claude), claude or "未检测到",
              "安装并登录 Claude Code CLI", blocking=False),
        Check("codex CLI", bool(codex), codex or "未检测到",
              "安装并登录 OpenAI codex CLI", blocking=False),
        Check("至少一个模型后端", bool(claude or codex),
              "claude/codex 至少装一个", "安装 claude 或 codex 其一"),
    ]
    return checks


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.blocking)
