# Spec B · 引导门户 + UI 重做（qun-alpha onboarding + UI）— 设计文档

**日期**：2026-05-29
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

让工具"不止我自己能用，链接发给任何人也能照着跑起来"，并把界面做得好看、有动画交互。采用**模式 X**：线上链接是引导门户（教别人在自己电脑上装+跑），不做模式 Y（线上远程驱动本地 agent）。

UI 风格参考 `~/real-ai-writer-mockup.html`：Catppuccin 配色（Latte 浅 + Mocha 深双主题）、等宽字体（Maple Mono / JetBrains Mono）、mauve 紫主色、柔和阴影。

## 2. 范围

做：
- B1 手把手 onboarding 向导页（静态，含安装 wechat-decrypt 包步骤）。
- B2 本地操作台 UI（`qun_alpha/static/index.html`）按 mockup 重做 + 动画交互。

不做：模式 Y（线上驱动本地 agent 的跨域+配对+安全）；后端检测用户本机状态（静态页做不到）；飞书 UI。

## 3. B1 — onboarding 向导页（`landing/index.html` 重做）

- Catppuccin 浅/深双主题（顶部切换按钮）+ 等宽字体 + 柔和阴影，对齐 mockup。
- **分步向导**，每步：标题 + 说明 + 命令代码块 + 「复制」按钮 + 可勾选打勾；平滑展开/推进动画；顶部步骤进度。
- 步骤一条龙：
  0. 前置：Python 3.10+ / `xcode-select --install`
  1. **装 wechat 解密包**：`git clone https://github.com/ylytdeng/wechat-decrypt ~/wechat-research/ylytdeng-wechat-decrypt` + 装其依赖（venv + `pip install -r requirements.txt`）
  2. 装 qun-alpha：clone + `python3 -m venv .venv` + `pip install -e .`
  3. 解密导出微信（含 sudo 提醒）：`killall WeChat` → `codesign 重签名` → 编译扫描器 → `sudo ./find_all_keys_macos` → `python3 decrypt_db.py` → `python3 export_all_chats.py <out>`
  4. `qun-alpha import-export --src-dir <out> --groups-only`
  5.（可选）配 Notion：`cp config.example.json config.json` 填 token → `qun-alpha init-notion`
  6. `qun-alpha serve` → 开 http://127.0.0.1:7800 → 用
- 纯静态：交互 = 前端步骤导航 + 复制按钮 + 打勾进度 + 主题切换 + 动画；**不检测本机真实状态**。
- 免责声明：仅分析自己的微信数据。

## 4. B2 — 本地操作台 UI 重做（`qun_alpha/static/index.html`）

- 同一套 Catppuccin/等宽设计 token，浅/深主题切换。
- 动画交互：进度条平滑填充 + 抽取时脉冲/spinner、群列表卡片 hover、结果淡入、阶段日志自动滚动。
- 功能不变（选群→跑→进度→结果），换皮 + 预留 Spec A 的"跑前预估面板"与"resume/增量"入口位（接口待 Spec A 落地后接线；本 spec 先放占位与样式）。
- 保留现有错误提示与空选群提示逻辑。

## 5. 共享设计 token

两页因托管位置不同（landing 静态托管 / serve 本地服务）各自内联**同一段** Catppuccin 设计 token（CSS 变量：颜色/阴影/字体/主题切换逻辑），保证视觉一致。token 块以注释标注"两处需同步"。

## 6. 错误处理 / 边界
- 向导页是静态说明，无运行时错误面。
- 操作台沿用现有：起任务失败显示后端 error、空选群提示。
- 主题选择存 localStorage，刷新保持。

## 7. 测试
- 后端接口不变，沿用现有测试。
- 操作台 smoke：`GET /` 返回 200、含关键元素 id（groups/start/bar）、含主题切换元素。
- 向导页：静态文件，人工视觉验收为主；可加一个"文件存在且含 6 个步骤锚点"的轻量检查。
- 纯 HTML/CSS/JS 不强行 TDD；以用户视觉验收为准。

## 8. 未来（不在本 spec）
模式 Y（线上操作台 + 本地 agent 配对）、向导页按平台分支（Windows/Linux）、i18n。
