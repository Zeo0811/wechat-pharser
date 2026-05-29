# Spec A · 模型后端可选（Claude / Codex）— 设计文档

**日期**：2026-05-29
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

抽取实体时目前写死调 `claude -p`。要支持用户在 **Claude（`claude -p`）** 与 **Codex（OpenAI `codex exec`）** 之间选择：config 记录选择，运行时按选择调对应 CLI，扫描时检测哪些可用。本 spec 是"可分发产品"三步（A 模型后端 / B 安装器 / C 网页增强）的第一步、地基。

## 2. 范围

做：runner 抽象（claude/codex）+ 可用性检测 + config 字段 + 鲁棒 JSON 提取 + `qun-alpha model` 命令 + `analyze --model` + web 用 config 选择的后端。
不做：codex 的自动安装（B）；网页上的模型选择 UI（C 或后续，A 先用 config/命令切换）。

## 3. 组件

| 模块 | 职责 |
|---|---|
| `runners.py`（新） | `claude_runner(prompt)->str`（`claude -p <prompt>`）；`codex_runner(prompt)->str`（`codex exec <prompt>`）；`BACKENDS=["claude","codex"]`；`get_runner(backend)->callable`（未知名报错）；`detect_available()->list[str]`（`shutil.which`）。两个 runner 都注入 `_run`(subprocess) 便于 mock |
| `config.py`（改） | 加 `model_backend: str = "claude"` |
| `extractor.py`（改） | `_parse` 改鲁棒：先尝试整段 JSON；失败则抓最外层 `[...]`（首个 `[` 到末个 `]`）再 parse。兼容 codex/claude 可能夹带的过程文本。`default_claude_runner` 保留（=claude_runner 别名）以不破坏现有调用 |
| `web.py`（改） | `_default_target_factory` 用 `runners.get_runner(cfg.model_backend)`；`get_runner`/runner 调用失败（CLI 缺失）→ 现有 400/error 通道给人话 |
| `cli.py`（改） | `qun-alpha model`：打印可用后端 + 当前 config 选择；可选 `--set <backend>` 写回 config。`analyze` 加 `--model` 覆盖本次 |

### 边界决策
- runner 接口不变：`(prompt:str)->str`，与现有 `extract_chunk(runner=...)` 完全兼容。
- 鲁棒 JSON 提取是必须项：codex `exec` 输出常含过程文本，旧"整段即 JSON"会失败。
- backend 选择优先级：`analyze --model` > config.model_backend > 默认 "claude"。

## 4. 数据流

`extract_chunk` 调注入的 runner（不感知后端）→ runner 由 `get_runner(backend)` 决定 → claude_runner/codex_runner 各自拼命令、subprocess 跑、返回 stdout → `_parse` 鲁棒抽取 JSON 数组 → RawEntity[]。

## 5. 错误处理
- 选定 backend 的 CLI 不在 PATH（`detect_available` 查不到）→ 起任务/分析前明确报错："未检测到 <backend> CLI，请安装登录，或用 `qun-alpha model --set claude` 切换"。
- runner 输出 parse 失败 → 沿用现有"重试一次 + 兜底跳过"。

## 6. 测试
- `runners`：mock `_run`，断言 `claude_runner` 构造 `["claude","-p",prompt]`、`codex_runner` 构造 `["codex","exec",prompt]`；`get_runner("claude"/"codex")` 路由正确、未知名 raise；`detect_available` 用 monkeypatch `shutil.which`。
- 鲁棒 `_parse`：输入"前后带文字的 JSON 数组" → 成功抽出；纯 JSON 仍可；非法 → None。
- `config` 默认 `model_backend=="claude"`。
- `cli model` 命令返回可用列表 + 当前选择（注入 detect + config）。
- 全部不调真 claude/codex。

## 7. 未来（不在 A）
- B：安装器检测/引导安装 codex。
- C：网页模型选择下拉。
- 更多后端（gemini cli 等）只需加 runner + 注册。
