# Spec C · 网页群选择增强（搜索/全选/已处理状态）— 设计文档

**日期**：2026-05-29
**状态**：设计待用户 review

## 1. 背景与目标

群有 1560 个，网页选群体验要改善：**搜索框** + **全选/多选** + **已处理状态徽标**（哪些群分析过、跑过几次、最近何时）。顺带修一个现有 bug：web 起任务时没记录选了哪些 group_ids，导致无法标记"已处理"。可分发产品三步的第三步（A✓/B✓/C）。

## 2. 范围

做：`processed_store`（落盘每群已分析状态）；`_default_target_factory` 成功后标记已处理；`/api/groups` 给每群附 processed 信息；前端搜索框 + 全选 + 已处理徽标。
不做：每群"机会数"细分（当前抽取是多群合并聚合，无单群计数）；服务端分页（1560 个前端过滤即可）。

## 3. 组件

| 模块 | 改动 |
|---|---|
| `processed_store.py`（新） | `ProcessedStore(path=".qun_state/processed.json")`：`mark(group_ids, when=None)` 每群 runs+1、记 last 时间；`get(gid)->{"runs","last"}|None`；`all()->dict`。文件落盘（多实例同文件，与 cursor_store/job_store 一致）|
| `web.py`（改） | `_default_target_factory` 的 target：`run_job` 成功后 `ProcessedStore().mark(params["group_ids"])`；`/api/groups` 用 `ProcessedStore()` 给每群加 `processed`(bool)/`runs`/`last` |
| `static/index.html`（改） | 群卡片上方加搜索输入（前端过滤）+「全选/全不选」；每群标题后显示 `已分析·N次` 徽标（来自 /api/groups 的 processed） |

### 边界决策
- `processed_store` 文件落盘、多实例同文件——target 线程里写、/api/groups 里读，靠文件一致（与 cursor_store 同模式）。
- 已处理 = "该群被纳入过某次成功分析"（按 group_id），不细分单群机会数。
- 搜索/全选纯前端（1560 个量级前端过滤足够，不做服务端分页）。
- `when` 时间戳由调用方传入/默认 `datetime.now().isoformat()`，测试可注入固定值。

## 4. 数据流

分析成功 → target 把本次 group_ids 在 processed_store 里 mark（runs+1, last=now）→ 下次 `/api/groups` 读 processed_store，给每群附 `{processed, runs, last}` → 前端渲染「已分析·N次」徽标。搜索框前端过滤群名；全选勾当前可见项。

## 5. 错误处理
- processed_store 读/写失败 → 不影响分析主流程（标记是辅助），吞掉异常记日志。
- group_ids 缺失（老任务）→ 不 mark，不报错。

## 6. 测试
- `processed_store`：tmp_path 测 mark/get/all、runs 累加、last 写入、缺省 get 返回 None、多实例同文件可见。
- `web /api/groups`：注入 groups_provider + 预置 processed_store（mark 过某群）→ 断言该群 `processed=True`、其余 False。
- 前端 smoke：`GET /` 含搜索框 id、全选按钮 id；含 processed 徽标渲染逻辑标记。
- 不碰真模型/真 Notion。

## 7. 未来（不在 C）
- 单群机会数（需 per-group 聚合，改 run_job 返回结构）。
- 服务端分页/排序（群更多时）。
- 已处理的"增量"联动（结合 cursor_store 显示"有 N 条新消息待分析"）。
