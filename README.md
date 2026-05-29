# qun-alpha · 群聊投资机会分析

从你自己的微信高质量群聊里，用**本地模型**（Claude 或 Codex）提炼潜在投资机会，整理成实体中心的情报 CRM。**聊天数据全程留在本机**，不上云。

> 仅支持 macOS，仅用于分析**你自己的**微信数据，请遵守相关法律法规。

## 安装（一行）

```bash
curl -fsSL https://raw.githubusercontent.com/Zeo0811/wechat-pharser/main/install/install.sh | bash
```

安装器会：检测/自动装依赖（Python ≥3.10、Xcode 命令行工具）→ clone 本体与解密包 → 建虚拟环境 → 编译密钥扫描器 → 检测并让你选模型后端（claude / codex）→ 把 `qun-alpha` 命令装到 `~/.local/bin`。

装完跑一次体检：

```bash
qun-alpha doctor
```

## 用法

```bash
qun-alpha serve          # 起本地操作台：http://127.0.0.1:7800
                         # 网页里：①重签名(首次) ②解密并导出 → 搜索/选群 → 预估 → 开始分析
qun-alpha decrypt-guide  # 若想手动解密：打印 macOS 解密步骤
qun-alpha model --set codex   # 切换模型后端（claude / codex）
```

写入 Notion（可选）：`cp config.example.json config.json` 填 `notion_token` → `qun-alpha init-notion` 建表填回 id → 网页取消"预演"勾选。

## 工作原理

1. **取密钥**（免 SIP）：ad-hoc 重签名微信后，用 Mach VM 扫进程内存，按 SQLCipher 的 `codec_ctx`（salt → 派生密钥）+ HMAC 校验提取每个数据库的密钥。支持微信 4.1。
2. **解密 + 导出**：SQLCipher 4 解密本地库，导出每会话 JSON。
3. **分析**：按群+时间切块 → 本地 `claude -p` / `codex exec` 逐块抽取「公司/人物/链接」→ 跨块去重、打分、分诊（emerging/known/noise/unclear）、合成 Signal。
4. **产出**：本地结果 + 可写 Notion 三张关联表（Companies / People / Links）。

## 命令一览

`serve` 本地操作台 · `analyze` 命令行分析 · `import-export` 转换导出 · `decrypt-guide` 解密说明 · `init-notion` 建 Notion 表 · `model` 切后端 · `doctor` 依赖体检

## 依赖

macOS · Python ≥3.10 · Xcode 命令行工具 · 微信 4.x（开着并登录）· Claude Code CLI 或 OpenAI Codex CLI（至少一个，需登录）

## 免责声明

本工具仅用于分析**自己的**微信数据，用于学习研究。请遵守相关法律法规，勿用于未授权的数据访问。
