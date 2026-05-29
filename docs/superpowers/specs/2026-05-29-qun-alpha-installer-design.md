# Spec B · curl 安装器 + 依赖体检（qun-alpha installer）— 设计文档

**日期**：2026-05-29
**状态**：设计待用户 review

## 1. 背景与目标

让任何人在 macOS 上**一行 `curl ... | bash`** 装好 qun-alpha：检测所有依赖，能自动装的自动装、不能的引导；clone 本体 + wechat-decrypt、建 venv、检测 claude/codex、把 `qun-alpha` 命令装到 PATH、首次选模型后端。配套一个 `qun-alpha doctor` 依赖体检命令（纯 Python，可测），install.sh 末尾调用它确认环境就绪。

可分发产品三步（A 模型后端✓ / B 安装器 / C 网页增强）的第二步。

## 2. 范围

做：`install/install.sh`（检测+自动装+clone+venv+编译预检+PATH 链接+首次选后端）；`qun-alpha doctor` 命令（体检报告）。
不做：自动装 Homebrew / Xcode CLT / claude / codex（只引导，因要 sudo 或登录）；非 macOS；发布到 npm（A 路线选了 curl）；Windows/Linux。

## 3. 依赖与处理策略

| 依赖 | 检测 | 缺失处理 |
|---|---|---|
| macOS | `uname` = Darwin | 非 mac 直接退出报错 |
| Xcode CLT（cc/git） | `xcode-select -p` | 跑 `xcode-select --install`（弹系统框）+ 提示装完重跑 |
| Python ≥3.10 | `python3 -V` / 找 `python3.12`/`python3.11` | 有 brew → `brew install python@3.12`；无 brew → 引导装 brew/python |
| Homebrew | `command -v brew` | 引导（装它要 sudo+确认） |
| qun-alpha 本体 | `~/.qun-alpha` 存在 | git clone（已存在则 `git pull`） |
| qun-alpha venv | `~/.qun-alpha/.venv` | `python3 -m venv` + `pip install -e .` |
| wechat-decrypt | `~/.qun-alpha/vendor/wechat-decrypt` | git clone（ylytdeng）|
| wechat-decrypt venv | 其 `.venv` 含 pycryptodome | 用 **python3.12** 建 venv + `pip install pycryptodome zstandard mcp`（实测全 requirements 需 3.10+，最小集即可解密导出）|
| find_keys_codec | 能否编译 | `cc` 预编译一次到 vendor 仓库，失败即报（早暴露编译问题）|
| claude CLI | `command -v claude` | 引导安装登录 |
| codex CLI | `command -v codex` | 引导安装登录 |
| 模型后端选择 | — | 若两者都在 → 交互问选哪个写 config；只一个 → 自动设它；都没 → 提示需装至少一个 |
| config.json | 存在 | 不存在则 `cp config.example.json config.json` |
| PATH 命令 | `command -v qun-alpha` | 软链 venv/bin/qun-alpha → `~/.local/bin/qun-alpha`（提示把 ~/.local/bin 加 PATH）；写不了则试 `/usr/local/bin` |

## 4. 组件

| 文件 | 职责 |
|---|---|
| `install/install.sh`（新） | 上表全流程；幂等（可重复跑）；彩色分步输出；末尾调 `qun-alpha doctor` |
| `qun_alpha/doctor.py`（新） | `check_all() -> list[Check]`：每项 {name, ok, detail, fix_hint}；纯函数（系统查询注入便于测）|
| `qun_alpha/cli.py`（改） | `qun-alpha doctor` 命令：跑 check_all 并彩色打印；有缺失 exit 非零 |
| `README.md` / `landing`（改） | 写上 `curl ... | bash` 一行安装（URL 待仓库公开后填）|

### 边界决策
- 安装根目录可用 `QUN_ALPHA_HOME` 环境变量覆盖（默认 `~/.qun-alpha`）。
- install.sh **幂等**：每步先检测再决定装/跳过，重复跑安全。
- `doctor` 的系统查询（which/版本/路径存在）抽成可注入函数，逻辑可 TDD；install.sh 本身以手动/冒烟为主。
- curl 一行在仓库公开前先支持「clone 后本地跑 `bash install/install.sh`」；公开后再补 raw URL 的 `curl|bash`。

## 5. 数据流（首次安装）

`curl ... | bash`（或本地 `bash install/install.sh`）→ 逐项检测 → 自动装能装的、引导不能装的 → clone+venv+编译预检 → 检测 claude/codex → 交互选后端写 config → 链接 `qun-alpha` 到 PATH → 跑 `qun-alpha doctor` 出体检报告 → 打印下一步（`qun-alpha serve` / `qun-alpha decrypt-guide`）。

## 6. 错误处理
- 任一「只能引导」的依赖缺失：打印明确的人话修复指令 + 装好后重跑安装器即可（幂等）。
- 编译预检失败：报错指向 Xcode CLT。
- 网络/clone 失败：报错 + 重试提示。

## 7. 测试
- `doctor.check_all`：注入假的 which/版本/路径，断言各项 ok/缺失判定 + fix_hint 文案；纯逻辑。
- `qun-alpha doctor` 命令：注入 check_all 返回，断言打印 + 退出码（有缺失非零）。
- install.sh：`bash -n install/install.sh` 语法检查（计划里作为一步）；真实端到端由用户在干净环境冒烟（不进 CI）。

## 8. 未来（不在 B）
- 发布 npm 包（同一 install 逻辑包一层）。
- 自动装 codex/claude（若它们将来支持无登录的 headless 安装）。
- Linux/Windows 分支。
