# Spec A · 大任务扛量（qun-alpha scale handling）— 设计文档

**日期**：2026-05-29
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

真实场景里群多、数据量大，一次任务可能跑几小时、中途中断，或需要日常只处理新消息。目标：让大任务**可重复、可续、可增量、可预估**，不重复烧钱。

复用已有的 extractor 块级磁盘缓存（按 `chunk_id` 缓存抽取结果，重跑自动跳过已完成块）。本 spec 在其上补落盘、游标、预估、并发。

## 2. 范围

做：任务状态落盘 + resume + 增量游标 + 跑前规模/成本预估 + 有界并发抽取。
不做：精确字节级断点（用"重跑+缓存跳过"代替）；分布式；跨机调度。

## 3. 组件

| 模块 | 职责 | 输入→输出 | 依赖 |
|---|---|---|---|
| `job_store`（新） | 任务记录落盘 `.qun_jobs/<id>.json`：params/status/done_chunk_ids/failed_chunk_ids/result/created_at | Job → 磁盘 | json/os |
| `cursor_store`（新） | 每群增量游标 `.qun_state/cursors.json`：group_id → last_timestamp | get/set | json/os |
| `estimate`（新） | 跑前预估：块数、其中已缓存数、预计 token/$/分钟 | (export_path, group_ids, start, end, max_messages, cache_dir) → dict | chat_reader |
| `orchestrator.run_job`（改） | ①完成块即写 job_store ②有界并发抽取（默认 3）③成功后更新游标 | 同现有 + job_store/并发参数 | 上述 |
| `JobManager`（改） | 背后接 job_store；新增 `resume(job_id)` 用原 params 重跑 | — | job_store |

### 边界决策
- **resume = 用原 params 重跑**，靠块缓存跳过已完成块（轻量，不做精确断点）。
- **游标只在整群成功后更新**，避免半途更新漏数据。
- **并发默认 3**（有界线程池跑 `claude -p`），防 API 限速；可配置。
- estimate 的 token/$ 是**粗估**（按每块平均 token × 可配置单价），用于"别一点就懵"，非精确账单。

## 4. 数据流

**存量回溯 + 中断续跑**：选群 → estimate 显示"约 N 块 / 已缓存 M / 预计 $X / 约 Y 分钟" → 确认 → 跑，每块完成即落盘 → 中途停/崩 → 任务列表显示"未完成" → resume → 重跑同 params，缓存跳过已完成块，只补剩余 + failed。

**日常增量**：勾"增量" → 每个选中群从 cursor_store 读上次时间戳，只处理之后的新消息 → 跑 → 整群成功后游标推进到本次最新。

## 5. 错误处理
- 单块失败 → 记入 job 的 failed 列表，不拖垮整批；报告列出失败块；resume 时优先补 failed + 未跑块。
- 模型 JSON 不合规 → 沿用现有重试一次 + 兜底跳过。
- job_store/cursor_store 写失败 → 记录但不中断任务（落盘是辅助，缓存仍保证可续）。

## 6. 测试
- `job_store` / `cursor_store`：tmp_path 测存取、缺文件默认、并发安全（简单锁）。
- `estimate`：fixture 算块数 + 缓存命中数，断言字段齐全、缓存命中减少预估。
- `orchestrator`：fake runner 测「完成块落盘」「resume 跳过缓存只补剩余」「游标只在成功后推进」「有界并发不超限」。
- 全部不碰真模型/真 Notion。

## 7. 未来（不在本 spec）
精确断点、分布式抽取、实时增量监听、成本真实计量（接 API 用量回报）。
