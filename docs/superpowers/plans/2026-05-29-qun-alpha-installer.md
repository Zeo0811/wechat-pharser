# Spec B curl 安装器 + 依赖体检 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 一行 `curl|bash` 安装 qun-alpha：检测/自动装依赖、clone 本体+wechat-decrypt、建 venv、检测 claude/codex、装命令到 PATH、首次选后端；配 `qun-alpha doctor` 依赖体检。

**Architecture:** `doctor.py` 是纯逻辑（系统查询注入便于测）输出体检项；`qun-alpha doctor` 命令打印+退出码；`install/install.sh` 是幂等 shell 安装器，末尾调 doctor。

**Tech Stack:** Python（os/shutil/sys，stdlib）、typer、pytest、bash。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/doctor.py   # 新：Check + check_all(注入探针) + all_ok
qun_alpha/cli.py      # 改：doctor 命令
install/install.sh    # 新：幂等安装器
tests/test_doctor.py  # 新
```

---

## Task 1: doctor.py 依赖体检（纯逻辑）

**Files:** Create `qun_alpha/doctor.py`; Test `tests/test_doctor.py`

- [ ] **Step 1: 写失败测试 `tests/test_doctor.py`**

```python
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
    # 只有 claude：个体 codex 项失败但不阻塞；"至少一个后端" 通过
    checks = check_all(system="Darwin", which=_which({"cc", "git", "claude"}),
                       exists=lambda p: True, py_ge_310=True, home="/h")
    assert all_ok(checks)                       # codex 缺失不阻塞
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
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_doctor.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/doctor.py`**

```python
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
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_doctor.py -q` → Expected: 6 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/doctor.py tests/test_doctor.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: doctor 依赖体检(纯逻辑+注入探针)"
```

---

## Task 2: cli doctor 命令

**Files:** Modify `qun_alpha/cli.py`; Test `tests/test_doctor.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_doctor.py` 末尾**

```python
def test_render_doctor_lines():
    from qun_alpha.cli import render_doctor
    checks = [Check("macOS", True, "Darwin"),
              Check("Xcode 命令行工具", False, "cc=None", "运行：xcode-select --install")]
    lines, ok = render_doctor(checks)
    assert ok is False
    body = "\n".join(lines)
    assert "macOS" in body and "Xcode" in body
    assert "xcode-select" in body          # 缺失项带修复提示
    assert "✅" in body and "❌" in body
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_doctor.py::test_render_doctor_lines -q` → Expected: ImportError (render_doctor)

- [ ] **Step 3: 修改 `qun_alpha/cli.py`**

(a) 顶部 import 增加 doctor：把
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service, runners
```
改为
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service, runners
from qun_alpha import doctor as doctor_mod
```

(b) 在 `if __name__ == "__main__":` 之前追加：
```python
def render_doctor(checks) -> tuple[list, bool]:
    lines = []
    for c in checks:
        mark = "✅" if c.ok else "❌"
        line = f"{mark} {c.name}: {c.detail}"
        if not c.ok and c.fix:
            line += f"  → {c.fix}"
        lines.append(line)
    return lines, doctor_mod.all_ok(checks)


@app.command()
def doctor():
    """依赖体检：检查 macOS / Xcode CLT / Python / claude·codex / 安装目录。"""
    checks = doctor_mod.check_all()
    lines, ok = render_doctor(checks)
    for ln in lines:
        typer.echo(ln)
    if not ok:
        typer.echo("\n有阻塞项未满足，请按上面提示修复后重试。")
        raise typer.Exit(1)
    typer.echo("\n✅ 环境就绪。")
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_doctor.py -q` → Expected: 7 passed
Run: `.venv/bin/pytest -q` → Expected: 全绿
验证：`.venv/bin/python -c "from qun_alpha.cli import app, render_doctor; print('ok')"`

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/cli.py tests/test_doctor.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: qun-alpha doctor 命令"
```

---

## Task 3: install/install.sh 安装器

**Files:** Create `install/install.sh`; Test `tests/test_install_sh.py`

- [ ] **Step 1: 写测试 `tests/test_install_sh.py`（语法 + 关键步骤存在）**

```python
import subprocess
from pathlib import Path

SH = Path("install/install.sh")


def test_install_sh_syntax_ok():
    # bash -n 仅做语法检查，不执行
    r = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_install_sh_has_key_steps():
    t = SH.read_text(encoding="utf-8")
    for kw in ["Darwin", "xcode-select", "git clone", "venv",
               "find_keys_codec", "claude", "codex", "qun-alpha doctor",
               "QUN_ALPHA_HOME", ".local/bin"]:
        assert kw in t, f"缺少关键步骤: {kw}"
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_install_sh.py -q` → Expected: FAIL（文件不存在）

- [ ] **Step 3: 创建 `install/install.sh`**

```bash
#!/usr/bin/env bash
# qun-alpha 安装器（macOS）。幂等，可重复运行。
# 用法：curl -fsSL <RAW_URL>/install/install.sh | bash
#   或：bash install/install.sh
set -euo pipefail

QUN_ALPHA_HOME="${QUN_ALPHA_HOME:-$HOME/.qun-alpha}"
QUN_REPO="${QUN_REPO:-https://github.com/your/qun-alpha}"   # 仓库公开后填真实地址
WD_REPO="https://github.com/ylytdeng/wechat-decrypt"
VENDOR="$QUN_ALPHA_HOME/vendor/wechat-decrypt"
BIN_DIR="$HOME/.local/bin"

c() { printf "\033[1;35m▸ %s\033[0m\n" "$*"; }     # 紫色步骤
ok() { printf "  \033[32m✓ %s\033[0m\n" "$*"; }
warn() { printf "  \033[33m! %s\033[0m\n" "$*"; }

# 1. macOS
[ "$(uname)" = "Darwin" ] || { echo "本工具目前仅支持 macOS"; exit 1; }
c "检测系统：macOS ✓"

# 2. Xcode 命令行工具（cc/git）
if ! xcode-select -p >/dev/null 2>&1; then
  warn "未装 Xcode 命令行工具，正在唤起安装（会弹系统框）…装完请重跑本脚本"
  xcode-select --install || true
  exit 1
fi
ok "Xcode 命令行工具"

# 3. Python ≥3.10
PY=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys;print(sys.version_info>=(3,10))') || v=False
    [ "$v" = "True" ] && { PY="$cand"; break; }
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    c "用 brew 安装 python@3.12"; brew install python@3.12; PY=python3.12
  else
    echo "需要 Python ≥3.10。请先装 Homebrew (https://brew.sh) 再重跑，或自行安装 python3.12"; exit 1
  fi
fi
ok "Python：$PY"

# 4. clone / 更新 qun-alpha
c "安装 qun-alpha 到 $QUN_ALPHA_HOME"
if [ -d "$QUN_ALPHA_HOME/.git" ]; then
  git -C "$QUN_ALPHA_HOME" pull --ff-only || warn "git pull 跳过"
else
  git clone "$QUN_REPO" "$QUN_ALPHA_HOME"
fi

# 5. qun-alpha venv
"$PY" -m venv "$QUN_ALPHA_HOME/.venv"
"$QUN_ALPHA_HOME/.venv/bin/pip" install -q --upgrade pip
"$QUN_ALPHA_HOME/.venv/bin/pip" install -q -e "$QUN_ALPHA_HOME"
ok "qun-alpha venv + 依赖"

# 6. wechat-decrypt + 其 venv（解密/导出用）
c "安装 wechat-decrypt 到 $VENDOR"
if [ -d "$VENDOR/.git" ]; then git -C "$VENDOR" pull --ff-only || true; else git clone "$WD_REPO" "$VENDOR"; fi
"$PY" -m venv "$VENDOR/.venv"
"$VENDOR/.venv/bin/pip" install -q --upgrade pip
"$VENDOR/.venv/bin/pip" install -q pycryptodome zstandard mcp
ok "wechat-decrypt venv + 解密依赖"

# 7. 编译 find_keys_codec 预检
c "编译密钥扫描器（预检）"
if cc -O2 -o "$VENDOR/find_keys_codec" "$QUN_ALPHA_HOME/qun_alpha/native/find_keys_codec.c" -framework Foundation; then
  ok "find_keys_codec 编译通过"
else
  warn "编译失败，请确认 Xcode 命令行工具完整"
fi

# 8. 检测 claude / codex + 选后端
HAS_CLAUDE=$(command -v claude >/dev/null 2>&1 && echo 1 || echo 0)
HAS_CODEX=$(command -v codex >/dev/null 2>&1 && echo 1 || echo 0)
[ -f "$QUN_ALPHA_HOME/config.json" ] || cp "$QUN_ALPHA_HOME/config.example.json" "$QUN_ALPHA_HOME/config.json"
BACKEND=""
if [ "$HAS_CLAUDE" = 1 ] && [ "$HAS_CODEX" = 1 ]; then
  printf "检测到 claude 和 codex，用哪个？[claude]/codex: "; read -r ans </dev/tty || ans=""
  BACKEND="${ans:-claude}"
elif [ "$HAS_CLAUDE" = 1 ]; then BACKEND="claude"
elif [ "$HAS_CODEX" = 1 ]; then BACKEND="codex"
else warn "未检测到 claude 或 codex，请装并登录其一后再分析"; fi
if [ -n "$BACKEND" ]; then
  "$QUN_ALPHA_HOME/.venv/bin/qun-alpha" model --set "$BACKEND" --config-path "$QUN_ALPHA_HOME/config.json" >/dev/null 2>&1 || true
  ok "模型后端：$BACKEND"
fi

# 9. 链接 qun-alpha 命令到 PATH
mkdir -p "$BIN_DIR"
ln -sf "$QUN_ALPHA_HOME/.venv/bin/qun-alpha" "$BIN_DIR/qun-alpha"
case ":$PATH:" in
  *":$BIN_DIR:"*) ok "qun-alpha 已在 PATH（$BIN_DIR）";;
  *) warn "把 $BIN_DIR 加入 PATH：echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc";;
esac

# 10. 体检 + 下一步
c "依赖体检"
"$QUN_ALPHA_HOME/.venv/bin/qun-alpha" doctor || true
echo
c "完成！下一步："
echo "  qun-alpha decrypt-guide   # 看解密说明"
echo "  qun-alpha serve           # 起本地操作台 http://127.0.0.1:7800"
```

注意：第 8 步用到 `qun-alpha model --set ... --config-path`。当前 `model` 命令的 config 参数名是 `--config-path`？实际 Spec A 里是 `config_path: str = typer.Option("config.json")` → typer 生成 `--config-path`。一致。

- [ ] **Step 4: chmod + 运行确认通过**
```bash
chmod +x install/install.sh
```
Run: `.venv/bin/pytest tests/test_install_sh.py -q` → Expected: 2 passed
Run: `bash -n install/install.sh` → Expected: 无输出、退出 0

- [ ] **Step 5: 全套**
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 6: Commit**
```bash
git add install/install.sh tests/test_install_sh.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: install.sh 一行 curl 安装器(检测/自动装/编译/选后端/PATH/doctor)"
```

---

## 完成标准（Spec B）
- [ ] `pytest -q` 全绿
- [ ] `doctor.check_all` 各项判定 + fix 提示正确；`all_ok` 忽略非阻塞项（个体 claude/codex）
- [ ] `qun-alpha doctor` 命令打印体检 + 有阻塞项退出非零
- [ ] `install/install.sh` 语法 OK、含全部关键步骤、幂等
- [ ] 既有测试不回归

## 后续（不在 B）
- 仓库公开后把 `QUN_REPO` 与 README 里的 raw URL 填实，curl 一行才真正可用。
- 发布 npm 包（包同一逻辑）。
- Spec C：网页搜索/全选/多选 + 已处理状态。
