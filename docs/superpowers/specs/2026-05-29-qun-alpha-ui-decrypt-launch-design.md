# Spec C · UI 解密启动入口（qun-alpha UI decrypt launch）— 设计文档

**日期**：2026-05-29
**状态**：设计已确认，待写实现计划

## 1. 背景与目标

让用户在本地操作台直接点按钮跑真实解密导出流程，不用复制命令到终端。`qun-alpha serve` 是本机进程，可 subprocess 执行命令；需 root 的步骤用 macOS 原生授权弹窗（osascript `do shell script ... with administrator privileges`）。

## 2. 绕不开的约束与拆分

codesign 重签名要求**微信关闭**；提密钥扫描要求**微信开着且已登录**。无法无脑一条龙，故拆两段：
- **① 一次性重签名**（很少点）：killall 微信 + ad-hoc 重签名。完成后用户需手动重开并登录微信。
- **② 日常解密导出**（常用一键）：提密钥 → 解库 → 导出 → 转格式 → 自动加载群。

## 3. 范围

做：两个后端端点（codesign / decrypt-export）复用 Job+SSE；osascript 管理员授权封装；操作台"解密微信"卡片；失败人话提示；结束自动加载群。
不做：自动检测"微信已登录"（无法可靠判断，靠扫描失败提示）；Windows/Linux（仅 macOS）；自动安装 wechat-decrypt 包（缺失则提示）。

## 4. 组件

| 模块 | 职责 |
|---|---|
| `decrypt_service`（改） | 加 `admin_wrap(cmd)` 把命令包成 osascript 管理员授权；加 `codesign_steps()` 与 `decrypt_export_steps(repo_dir, out_dir, qun_export_path)` 返回有序命令列表；沿用 `classify_error` |
| `decrypt_runner`（新，或并入 decrypt_service） | `run_sequence(steps, runner, emit)`：按序跑命令，每步 emit 进度，任一步非零退出即抛含 stderr 的错误 |
| `web`（改） | `POST /api/codesign`、`POST /api/decrypt-export`：构造 steps → 起 Job（复用 JobManager/SSE）→ decrypt-export 成功后结果含可加载的 export 路径 |
| `config`（改） | 加 `wechat_decrypt_repo`(默认 `~/wechat-research/ylytdeng-wechat-decrypt`)、`raw_export_dir`(默认 `exported_chats/raw`)、`export_path`(默认 `exported_chats/all.json`) |
| `static/index.html`（改） | "解密微信"卡片：①重签名 ②解密导出 两按钮 + 复用进度条/日志；②完成后自动调用 `/api/groups` 加载群 |

### 边界决策
- osascript 以 root 跑的命令是**代码固定拼装**，仅 repo/out 路径来自本地 config；不接受网页传入任意命令。
- 仅 `127.0.0.1` 本地自用。
- 命令拼装注意 shell 引号转义（osascript 内层 `do shell script "..."` 的双引号转义、路径含空格）。

## 5. 命令序列

**codesign（①）**：
```
killall WeChat || true
osascript -e 'do shell script "codesign --force --deep --sign - /Applications/WeChat.app" with administrator privileges'
```

**decrypt-export（②）**（repo=R, out=O, export=E）：
```
cc -O2 -o R/find_all_keys_macos R/find_all_keys_macos.c -framework Foundation
osascript -e 'do shell script "cd R && ./find_all_keys_macos" with administrator privileges'
cd R && python3 decrypt_db.py
cd R && python3 export_all_chats.py O
qun-alpha import-export --src-dir O --out-path E --groups-only
```
（编译不需 root；提密钥需 root；其余不需。每步独立 subprocess。）

## 6. 数据流

操作台点 ② → `POST /api/decrypt-export` → 构造 steps → JobManager.start → 后台按序跑（osascript 弹一次管理员密码）→ SSE 推每步进度 → 成功 → 前端自动 `GET /api/groups?export_path=E` 把群加载出来 → 用户选群分析。

## 7. 错误处理
- 每步非零退出 → 抛错带 stderr → `classify_error` 翻人话（微信没开/没重签名/没装包/已取消）→ SSE error 事件 → UI 显示。
- 用户密码框取消 → osascript 非零 → 提示"已取消授权"。
- repo 路径不存在 → 预检报错提示去装（指向引导页）。

## 8. 测试
- `admin_wrap` / `codesign_steps` / `decrypt_export_steps`：纯字符串，断言含 `administrator privileges`、顺序、路径注入、转义。
- `run_sequence`：mock runner（含一步失败场景），断言按序执行、失败即停并带 stderr、emit 进度。
- web 端点：TestClient + 注入 fake step-runner，断言起 Job、成功结果含 export 路径、失败 → error。
- 真实解密执行不进 CI（手动验收）。

## 9. 未来（不在本 spec）
自动检测微信登录态；首次缺包时一键 clone wechat-decrypt；Windows/Linux 分支；并行多账号。
