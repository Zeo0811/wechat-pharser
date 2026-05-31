# Spec · 本地报告输出（Word+MD 到 Downloads，移除 Notion/预演）— 设计文档

**日期**：2026-05-31
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

分析结果改为**直接生成 Word + Markdown 两份报告存到 `~/Downloads`**；从分析流程**移除 Notion 写入和"预演"开关**。Notion 代码（notion_writer / init-notion 命令）保留备用但不在主流程。

## 2. 范围

做：`report.py`（md + docx via python-docx）；`run_job` 改为聚合后生成报告、移除 notion 写入与 dry_run；cli/web 去掉 dry_run/notion 传参、加 report_dir；前端去掉"预演"勾选 + 显示报告路径；加 python-docx 依赖；更新受影响测试。
不做：删除 notion_writer/init-notion 代码（保留备用）；自定义报告模板/路径 UI（固定 ~/Downloads）。

## 3. 组件

| 模块 | 改动 |
|---|---|
| `report.py`（新） | `write_reports(companies, people, links, out_dir=None, when=None)->{"md","docx"}`。out_dir 默认 `~/Downloads`；文件名 `群聊投资机会_<YYYY-MM-DD_HHMMSS>.{md,docx}`。md 字符串拼装；docx 用 **python-docx**。入参是聚合后的 Company/Person/Link 模型对象 |
| `pyproject.toml`（改） | 依赖加 `python-docx>=1.1,<2` |
| `orchestrator.run_job`（改） | 签名去掉 `notion_client/companies_db_id/people_db_id/links_db_id/dry_run`，加 `report_dir: Optional[str]=None`。聚合后 `emit("write","生成报告")` → `report.write_reports(...)` → result 用 `report_md`/`report_docx` 取代三个 `*_payloads` |
| `cli.py`（改） | `run_pipeline` 同步去 notion/dry_run、加 report_dir；`analyze` 去 `--dry-run`/notion_client、runner 不变、传 report_dir（默认 ~/Downloads）|
| `web.py`（改） | `_default_target_factory` 去 dry_run/notion_client/db_ids、传 report_dir；`run_job` 调用同步 |
| `static/index.html`（改） | 去掉"预演（不写 Notion）"勾选；POST /api/jobs 不再传 dry_run；完成时显示"已保存到 ~/Downloads：<md> / <docx>" |

### 边界决策
- 报告入参用**模型对象**（Company/Person/Link），不用 notion 格式 payload，更直接。
- run_job result：`{chunks, raw_entities, companies, people, links, report_md, report_docx}`。
- notion_writer 模块与 `init-notion` 命令**保留**（dormant），不在 run_job/analyze/serve 流程里调。
- 增量（incremental/cursor）逻辑**保留不变**。
- docx 用 python-docx（纯 Python，随 pip 装；安装器无需 node）。

## 4. 数据流

选群 → start（无 dry_run）→ run_job 聚合 → `report.write_reports` 写 `~/Downloads/群聊投资机会_<时间>.md` 与 `.docx` → result 带两路径 → 前端"完成"时显示路径。

## 5. 报告内容（沿用既有结构）
- 标题 + 统计（N 公司/人/链接，X 块）
- 一、公司（按 score 降序）：【score·status】name + 赛道/阶段/融资/投资方/建议 + Signal
- 二、人物：name（role）· 关联公司 · 金句
- 三、链接：title/url · 关联公司 · 分享者

## 6. 错误处理
- ~/Downloads 写失败 → run_job 抛错，经 SSE error 显示（不静默）。
- python-docx 缺失 → 安装器/依赖保证装上；import 失败给清晰错误。

## 7. 测试
- `report.write_reports`：tmp out_dir，喂构造的 Company/Person/Link → 断言生成 .md（含公司名/Signal）+ .docx（zip 可打开、含公司名）；文件名格式。
- `orchestrator.run_job`：fake runner，断言 result 含 `report_md`/`report_docx` 且文件存在（out_dir=tmp）；不再有 *_payloads；阶段事件仍含 write/done。
- `cli`/`web`：更新 test_cli_smoke / test_web（去 company_payloads 断言，改断言 report 路径）；smoke 前端不含"预演"。
- 不碰真模型/真 Notion。

## 8. 未来（不在本 spec）
- 可选 Notion 输出作为开关（命令/配置，非默认）。
- 报告模板可配置、CSV 导出。
