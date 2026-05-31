# Spec · 流程精简（自动加载群 + 解密优先 + 装完引导启动）— 设计文档

**日期**：2026-05-31
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

当前网页首屏要先填"导出 JSON 路径"再点"加载群列表"，多余且劝退。优化：网页打开**自动判断状态并加载群**；首次无数据时**突出解密入口**；CLI 装完**引导直接起服务进解密**。

## 2. 范围

做：`GET /api/config`（导出路径 + 是否已有导出）；网页首屏自动加载群 / 首次显示解密优先态、移除路径输入框与"加载群列表"按钮、卡片重排（解密→群→分析）；install.sh 末尾引导 + 可选自动 `serve`。
不做：自定义导出路径的网页 UI（高级用户走 CLI `analyze --export-path`）；改动解密/分析后端逻辑。

## 3. 组件

| 模块 | 改动 |
|---|---|
| `web.py`（改） | 新增 `GET /api/config` → `{export_path, has_export, model_backend}`（export_path 来自 config，has_export=该文件存在）。注入 config_loader 便于测 |
| `static/index.html`（改） | ① 卡片重排：解密微信 → 群列表 → 分析选项。② 移除"导出 JSON 路径"输入框 + "加载群列表"按钮。③ 页面加载时 `fetch /api/config`：`has_export` 为真 → 自动用 export_path 拉 `/api/groups` 显示群；为假 → 群区显示占位"解密导出后这里自动出现群"，并给解密卡片加"首次：先点②"高亮提示。④ start/estimate 用 config 的 export_path（不再读输入框）。⑤ ②解密导出成功后自动重新拉群（已有逻辑，保留）|
| `install/install.sh`（改） | 末尾改为明确"装好了 → 下一步"引导；并加一句 `read` [Y/n]（`</dev/tty`）询问"现在启动操作台吗"，是则 `exec qun-alpha serve`（会开浏览器）|

### 边界决策
- export_path 单一真相来自 config（`export_path` 字段）；网页不再让用户手输。
- 首次/无数据态：不报错，引导去解密。
- install 的 [Y/n] 从 `/dev/tty` 读（curl|bash 下 stdin 是管道），与现有"选后端"一致；默认 Y。
- 自动加载失败（如 /api/groups 读文件异常）→ 群区显示错误文案，不白屏。

## 4. 数据流

打开网页 → `GET /api/config` → 有导出：`GET /api/groups?export_path=<config>` → 渲染群（搜索/全选/徽标）；无导出：显示解密优先态。解密②成功 → 自动重拉群。分析 start/estimate 用 config 的 export_path。

## 5. 错误处理
- `/api/config`：config 缺失 → 返回 has_export=false + 默认 export_path，不抛。
- 前端 fetch 失败 → 群区显示"加载失败：…"，解密卡片仍可用。

## 6. 测试
- `web /api/config`：注入 config_loader（含 export_path）+ exists 探针 → 断言返回 export_path/has_export/model_backend。
- 前端 smoke：`GET /` 含 `/api/config` 调用、群占位文案、解密卡片在群卡片之前（顺序）、不再含旧的"加载群列表"按钮 id（`loadGroups` 可保留为内部函数但不作为可见首步）。
- install.sh：keyword 测含"启动"/"serve"引导 + `/dev/tty` read。
- 不碰真模型/真 Notion。

## 7. 未来（不在本 spec）
- 网页内一键"解密+分析"串成向导步骤条。
- 多账号/多导出切换。
