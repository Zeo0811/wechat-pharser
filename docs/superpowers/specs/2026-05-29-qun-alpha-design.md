# 群聊投资机会分析（qun-alpha）— 设计文档

**日期**：2026-05-29
**状态**：设计已确认，待写实现计划

---

## 1. 背景与目标

我们日常在大量高质量微信群里，群聊中夹带着大量潜在投资信号（早期项目融资、二级观点、行业趋势、deal flow）。

**目标**：把这些群聊数据读出来，用模型把潜在投资机会提炼成一个**实体中心的情报 CRM**（参考"小登群 CRM"形态：以公司/人为主体去重聚合，带 Score、提及次数、状态分诊、原文引用+点评），并写入 Notion 供查看与筛选。

**硬约束 / 安全边界**：
- 原始聊天记录、解密后的数据库、密钥 **永不离开本机**（不上 Railway、不入任何云存储）。
- 出本机的只有两类：① 喂给模型的文本片段（走可信 Claude API，用户已接受）；② 最终结构化结果 → Notion。
- 模型算力用用户**本地 Claude Code CLI**（headless `claude -p`）。

---

## 2. 范围（v1）

- **分析模式**：批量回溯（一次性/按需），选群 + 时间范围。实时监听留接口、不做。
- **输出目标**：Notion（关联数据库）。飞书留待后续。
- **部署形态**：模式 X —— Railway 上一个静态落地/安装引导页；真正的产品是用户本机的本地 CLI/agent，它启动 `localhost` 操作台并完成全部工作。"线上操作台远程驱动本地 agent"（模式 Y）作为验证后的升级，不在 v1。
- **输出实体**：三张关联表 —— Companies（核心）、People、Links。

### 非目标（v1 明确不做）
- 实时监听 / 推送
- 飞书双写
- 模式 Y 的"线上操作台 + 跨域驱动本地 agent"
- Timeline / Stats 视图（可后置）

---

## 3. 整体架构与数据流

全部在用户 Mac 本地运行，浏览器是 `localhost` 操作台。Railway 仅托管静态引导页。

```
┌─────────────────────── 用户的 Mac（全本地）──────────────────────┐
│   浏览器 localhost:7800                                          │
│   ┌──────────────────────────────────────┐                      │
│   │ 操作台 Web UI                          │                      │
│   │ ① 选群 + 时间范围  ② 看进度  ③ 看结果   │                      │
│   └───────────────┬──────────────────────┘                      │
│                   │ HTTP / SSE 进度流                             │
│   ┌───────────────▼──────────────────────┐                      │
│   │ 编排后端 orchestrator (FastAPI)         │                      │
│   │  管线 5 阶段，逐阶段推进度               │                      │
│   └──┬────────┬──────────┬─────────┬───────┘                     │
│  ┌───▼──┐ ┌──▼─────┐ ┌──▼──────┐ ┌▼──────────┐                  │
│  │解密  │ │读聊天   │ │Claude   │ │聚合/打分   │                  │
│  │(库) │ │(SQLite) │ │Code CLI │ │(纯Python) │                  │
│  └──────┘ └─────────┘ │headless │ └─────┬─────┘                  │
│   wechat-decrypt       └─────────┘       │                       │
└──────────────────────────┼───────────────┼──────────────────────┘
                           │ 仅 prompt+JSON │ 写入
                    Anthropic API      Notion API
```

### 5 阶段管线（= 进度条的 5 段）
1. **解密** — 调 wechat-decrypt 提密钥 + 解库（一次性；已解过可跳过）。
2. **抽取消息** — 按选中群 + 时间范围，从解密后的 SQLite 读出聊天，归一化、切块。
3. **Map（模型）** — 每块丢给 `claude -p`，吐出"提到的公司/人/链接 + 引用 + 点评" JSON。无状态、可并发、可缓存。
4. **Reduce（纯代码 + 模型辅助消歧）** — 跨块跨群去重聚合同一实体，算 Mntns、Score、Status，汇总 Signal。
5. **写 Notion** — 建/更新 Companies、People、Links 三张关联表。

---

## 4. 组件拆分

| 模块 | 职责 | 输入 → 输出 | 依赖 |
|---|---|---|---|
| `landing` | Railway 静态落地+安装引导页 | — | 无（纯静态） |
| `cli_launcher` | 命令行入口：起 localhost 操作台 + 自动开浏览器 | 命令 → 运行中的服务 | Typer |
| `decrypt_service` | 封装 wechat-decrypt：提密钥、解库、列可选群 | 无 → 群列表 / 解密状态 | wechat-decrypt |
| `chat_reader` | 从解密后 SQLite 按群+时间读消息，归一化，切块 | (群ids, 时间范围) → `MessageChunk[]` | sqlite3 |
| `extractor` | 调 `claude -p` headless 对单块抽取实体 | `MessageChunk` → `RawEntity[]` | Claude Code CLI |
| `aggregator` | 跨块去重合并、算 Mntns/Score/Status、汇总 Signal | `RawEntity[]` → `Company[]/Person[]/Link[]` | 纯 Python（可选模型消歧） |
| `notion_writer` | 写/更新 Notion 三张关联数据库 | 实体 → Notion 页面 | Notion API |
| `orchestrator` | 串 5 阶段，管状态机、推 SSE 进度、断点续跑 | UI 请求 → 进度事件流 | 以上全部 |
| `web` | FastAPI + 轻前端操作台：选群/进度/结果摘要 | — | orchestrator |

### 关键边界决策
- **extractor 只抽取、aggregator 才聚合打分**：模型无状态读单块；"怎么合并、怎么打分"全是确定性代码。这是稳定复现 CRM 质量的关键。
- **批量管线直接读 SQLite，不走 MCP**：MCP 留给未来实时监听线。
- **每个模块可独立喂假数据测试**。
- **extractor 带缓存**：块内容 + prompt 版本哈希命中即返回。

---

## 5. 数据模型（Notion 三张表 + 字段）

### Companies（主表）
| 字段 | 说明 |
|---|---|
| Score | 信号强度 0–100（+ 色点视觉） |
| Company | 主体名（跨群去重聚合） |
| Mntns | 提及次数 |
| Status | `emerging` / `known` / `noise` / `unclear` |
| Signal | 原文引用 + 模型点评（核心叙事字段） |
| First seen / Last seen | 首次 & 最近提及时间 |
| Sector 赛道 | AI / 消费 / crypto / 硬件 … |
| Stage 阶段 | 种子 / 天使 / A / B / 二级 / 基金募资 … |
| 财务信号 | 融资额 / 估值 / ARR（如 "~$10M ARR"、"2-3亿美金"） |
| 关键人物 | 关联 → People |
| 投资人动向 | 谁在追（拾象 / AI Fund / 字节 …） |
| 情绪倾向 | 看多 / 看空 / 分歧 |
| 催化剂 / 风险 | 利好 + 反面信号（如 "要被 dpsk 筛掉了"） |
| 建议动作 | chase / watch / pass / intro |
| 置信度 | 模型对该信号的把握（防幻觉） |
| 源引用 | 群 + 发言人 + 时间 + 可回链原文 |

### People（关联表）
创始人/投资人画像：角色、关联公司（→Companies）、可信度、金句、来源。

### Links（关联表）
群里分享的链接卡（融资稿/播客/招募）：标题、分享人、关联公司（→Companies）、时间。

> Companies ↔ People ↔ Links 通过 Notion relation 关联，用 Status/Score 做视图筛选，复刻参考 CRM 形态。

---

## 6. 规模、成本与错误处理

### 规模假设（默认，可在 UI 调）
- 典型任务：5–10 群 × 最近 30 天，几千~几万条消息。
- 切块：按"群 + 时间窗"，每块约 100 条或约 8K token；并发跑 Map，限并发防限流。

### 成本控制
- **预筛过滤**：进模型前用规则扔掉垃圾（红包/表情/"收到"/打卡）。
- **缓存**：块内容 + prompt 版本哈希，重跑命中不重复调用。
- **增量**：记住每群已分析到的 msg_id，下次只跑新增。
- **预估面板**：跑前 UI 显示"约 N 块 / 预计 $X / 预计 Y 分钟"，确认再跑。

### 错误处理
- 每阶段状态落盘（SQLite/JSON），任一步崩溃可**断点续跑**，不重解密。
- 单块抽取失败 → 标记重试，不拖垮整批；报告列出失败块。
- 模型 JSON 不合规 → 校验 + 自动重试一次 + 兜底跳过并记录。
- Notion 写入失败 → 退避重试，结果先存本地可手动重推。
- 解密类失败（微信没开 / 没重签名 / 没 sudo）→ UI 给人话指引，而非糊报错。

---

## 7. 技术栈

- **后端/CLI**：Python 3.10+（复用 wechat-decrypt 解密代码），FastAPI（localhost + SSE），Typer（`cli_launcher`）。
- **前端**：单页 + 原生 JS 或 Alpine.js，不上重框架。
- **模型调用**：`claude -p` headless（subprocess）。
- **存储**：本地 SQLite 存任务状态/缓存/增量游标；解密库只读。
- **Railway landing**：纯静态。
- **打包**：`pipx`/`uv` 一行安装；后续可 PyInstaller 单文件。

---

## 8. 测试策略（TDD）

- `aggregator`（去重/打分/分诊）—— **质量命门，最该重测**：喂构造的假 `RawEntity`，断言合并、Mntns、Score、Status。先写测试再实现。
- `chat_reader` —— 假 SQLite 库验证过滤/归一化/切块。
- `extractor` —— mock `claude -p` 输出验证 JSON 解析 + 不合规重试；另留少量真实模型集成测试（手动、不进 CI）。
- `notion_writer` —— mock Notion API 验证字段映射、关联、退避。
- `orchestrator` —— 全 mock 各模块，验证 5 阶段状态机 + 断点续跑。
- **端到端冒烟**：脱敏小样本聊天 JSON → 完整管线 → 预期实体（Notion dry-run）。

---

## 9. 安全须知

- `all_keys.json` 等密钥文件含明文 raw key，`chmod 0600`，禁提交 git / 分享。
- 解密后 `.db` 为明文，含全部联系人/群/消息，谨慎备份。
- macOS 对 WeChat.app 做 ad-hoc 重签名会使其失去官方签名（重装可恢复）。
- 工具仅用于分析**自己的**微信数据，遵守相关法律法规。

---

## 10. 未来升级路线

1. 模式 Y：线上操作台 + 跨域驱动本地 agent（需 localhost CORS/HTTPS 配对 + 域名白名单 + 配对 token 安全锁）。
2. 飞书多维表格双写。
3. 实时监听线（复用 wechat-decrypt 的 monitor + MCP）。
4. Timeline / Stats 视图。
