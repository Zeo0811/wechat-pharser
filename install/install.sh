#!/usr/bin/env bash
# qun-alpha 安装器（macOS）。幂等，可重复运行。
# 用法：curl -fsSL <RAW_URL>/install/install.sh | bash
#   或：bash install/install.sh
set -euo pipefail

QUN_ALPHA_HOME="${QUN_ALPHA_HOME:-$HOME/.qun-alpha}"
QUN_REPO="${QUN_REPO:-https://github.com/your/qun-alpha}"
WD_REPO="https://github.com/ylytdeng/wechat-decrypt"
VENDOR="$QUN_ALPHA_HOME/vendor/wechat-decrypt"
BIN_DIR="$HOME/.local/bin"

c() { printf "\033[1;35m▸ %s\033[0m\n" "$*"; }
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
    echo "需要 Python >=3.10。请先装 Homebrew (https://brew.sh) 再重跑，或自行安装 python3.12"; exit 1
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
echo "  qun-alpha doctor          # 运行体检"
echo "  qun-alpha decrypt-guide   # 看解密说明"
echo "  qun-alpha serve           # 起本地操作台 http://127.0.0.1:7800"
