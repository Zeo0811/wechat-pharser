# 群聊投资机会分析 — 解密引导 + 落地页 (Plan 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 因解密执行需要用户在 Mac 上 sudo + codesign，工具不替用户跑，而是给出确切命令序列（`decrypt-guide` 命令）并把常见报错翻成人话；外加一个 Railway 静态落地引导页（模式 X 的入口）。

**Architecture:** `decrypt_service.py` 是纯逻辑——`macos_steps(repo_dir, output_dir)` 返回 (说明, 命令) 步骤列表；`classify_error(stderr)` 把已知报错子串映射成人话提示。CLI `decrypt-guide` 打印步骤。落地页是纯静态 HTML。全部可 TDD（纯字符串逻辑，无副作用）。

**Tech Stack:** Python 3.10+，typer，pytest。沿用 `.venv`。

---

## File Structure
```
qun_alpha/
  decrypt_service.py   # 新：macos_steps() + classify_error()
  cli.py               # 改：增 decrypt-guide 命令
landing/
  index.html           # 新：Railway 静态落地引导页
  README.md            # 新：Railway 部署说明（静态）
tests/
  test_decrypt_service.py  # 新
```

---

## Task 1: decrypt_service（步骤 + 错误翻译）

**Files:**
- Create: `qun_alpha/decrypt_service.py`
- Test: `tests/test_decrypt_service.py`

- [ ] **Step 1: 写失败测试 `tests/test_decrypt_service.py`**

```python
from qun_alpha.decrypt_service import macos_steps, classify_error


def test_macos_steps_sequence():
    steps = macos_steps(repo_dir="/repo/wechat-decrypt", output_dir="/out/chats")
    cmds = [s["command"] for s in steps]
    joined = "\n".join(cmds)
    # 关键步骤都在，且顺序正确
    assert any("killall WeChat" in c for c in cmds)
    idx_sign = next(i for i, c in enumerate(cmds) if "codesign" in c)
    idx_scan = next(i for i, c in enumerate(cmds) if "find_all_keys_macos" in c and "sudo ./" in c)
    idx_decrypt = next(i for i, c in enumerate(cmds) if "decrypt_db.py" in c)
    idx_export = next(i for i, c in enumerate(cmds) if "export_all_chats.py" in c)
    assert idx_sign < idx_scan < idx_decrypt < idx_export
    # 路径被正确插入
    assert "/repo/wechat-decrypt" in joined
    assert "/out/chats" in joined
    # 每步都有人话说明
    assert all(s["desc"] for s in steps)
    # 末尾提示用 import-export 接回本项目
    assert any("import-export" in c for c in cmds)


def test_classify_error_known_patterns():
    assert "微信" in classify_error("could not find process 'WeChat'")
    assert "重签名" in classify_error("task_for_pid failed (5): not permitted")
    assert "sudo" in classify_error("Operation not permitted")
    assert "Xcode" in classify_error("cc: command not found")


def test_classify_error_unknown_passthrough():
    msg = classify_error("某种没见过的错误 xyz")
    assert "xyz" in msg          # 未知错误原样带出，便于排查
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_decrypt_service.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'qun_alpha.decrypt_service'`

- [ ] **Step 3: 实现 `qun_alpha/decrypt_service.py`**

```python
from __future__ import annotations

# (stderr 子串, 人话提示) —— 命中第一个即返回
_ERROR_HINTS = [
    ("could not find process", "微信没在运行：请先打开并登录微信 4.x，再重试。"),
    ("task_for_pid", "无法读取微信进程内存：需要先对 WeChat.app 做 ad-hoc 重签名"
                     "（sudo codesign --force --deep --sign - /Applications/WeChat.app），"
                     "并用 sudo 运行扫描器。"),
    ("not permitted", "权限不足：扫描内存需要 sudo，且 WeChat.app 需已重签名。"),
    ("operation not permitted", "权限不足：请用 sudo 运行，并确认已重签名 WeChat.app。"),
    ("cc: command not found", "缺少编译器：请先装 Xcode Command Line Tools："
                              "xcode-select --install。"),
    ("command not found", "缺少依赖命令：检查是否装了 Xcode Command Line Tools / Python3。"),
]


def macos_steps(repo_dir: str, output_dir: str) -> list[dict]:
    """返回 macOS 上提取密钥→解库→导出→接回本项目的步骤列表。
    每项 {desc, command}。工具不替用户执行（含 sudo），只给确切命令。"""
    return [
        {"desc": "1. 退出微信（释放数据库锁，便于读取内存）",
         "command": "killall WeChat"},
        {"desc": "2. 对微信做 ad-hoc 重签名（允许读取其进程内存）",
         "command": "sudo codesign --force --deep --sign - /Applications/WeChat.app"},
        {"desc": "3. 重新打开微信并登录，然后编译密钥扫描器",
         "command": f"cc -O2 -o {repo_dir}/find_all_keys_macos "
                    f"{repo_dir}/find_all_keys_macos.c -framework Foundation"},
        {"desc": "4. 扫描微信进程内存提取数据库密钥（需 sudo）",
         "command": f"cd {repo_dir} && sudo ./find_all_keys_macos"},
        {"desc": "5. 用提取到的密钥解密所有数据库",
         "command": f"cd {repo_dir} && python3 decrypt_db.py"},
        {"desc": "6. 导出全部聊天为每会话一个 JSON 到输出目录",
         "command": f"cd {repo_dir} && python3 export_all_chats.py {output_dir}"},
        {"desc": "7. 转换成本项目可读的单数组 JSON，然后就能 qun-alpha serve 了",
         "command": f"qun-alpha import-export --src-dir {output_dir} "
                    f"--out-path exported_chats/all.json --groups-only"},
    ]


def classify_error(stderr: str) -> str:
    """把解密相关 stderr 翻成人话提示；未知错误原样带出。"""
    low = stderr.lower()
    for needle, hint in _ERROR_HINTS:
        if needle in low:
            return hint
    return f"未识别的错误，原文：{stderr.strip()}"
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_decrypt_service.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add qun_alpha/decrypt_service.py tests/test_decrypt_service.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: decrypt_service macOS 步骤 + 错误翻译"
```

---

## Task 2: cli decrypt-guide 命令

**Files:**
- Modify: `qun_alpha/cli.py`
- Test: `tests/test_decrypt_service.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_decrypt_service.py` 末尾**

```python
def test_cli_decrypt_guide_returns_steps():
    from qun_alpha.cli import decrypt_guide
    steps = decrypt_guide(repo_dir="/repo/wd", output_dir="/out")
    assert isinstance(steps, list)
    assert len(steps) >= 6
    assert all("command" in s and "desc" in s for s in steps)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/pytest tests/test_decrypt_service.py::test_cli_decrypt_guide_returns_steps -q`
Expected: FAIL，`ImportError: cannot import name 'decrypt_guide'`

- [ ] **Step 3: 修改 `qun_alpha/cli.py`**

在顶部 import 把
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import
```
改为
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service
```

在 `if __name__ == "__main__":` 之前追加：
```python
@app.command("decrypt-guide")
def decrypt_guide(
    repo_dir: str = typer.Option("~/wechat-research/ylytdeng-wechat-decrypt",
                                 help="wechat-decrypt 仓库路径"),
    output_dir: str = typer.Option("exported_chats/raw",
                                   help="export_all_chats.py 的导出目录"),
) -> list:
    """打印 macOS 上提取密钥→解库→导出→接回本项目的确切命令（工具不替你跑 sudo）。"""
    import os
    steps = decrypt_service.macos_steps(
        repo_dir=os.path.expanduser(repo_dir), output_dir=output_dir)
    typer.echo("在 Mac 上依次执行（含 sudo 的需你亲自确认）：\n")
    for s in steps:
        typer.echo(s["desc"])
        typer.echo(f"    {s['command']}\n")
    return steps
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/pytest tests/test_decrypt_service.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 跑全套**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（约 59 passed：55 + decrypt_service 4）

- [ ] **Step 6: Commit**

```bash
git add qun_alpha/cli.py tests/test_decrypt_service.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: cli decrypt-guide 命令"
```

---

## Task 3: Railway 静态落地引导页

**说明**：模式 X 的线上入口——纯静态页，引导用户安装本地 CLI 并跑通流程。不含后端。

**Files:**
- Create: `landing/index.html`
- Create: `landing/README.md`

- [ ] **Step 1: 创建 `landing/index.html`**

```html
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊投资机会分析 · 本地工具</title>
<style>
  body { font-family: -apple-system, "PingFang SC", sans-serif; max-width: 680px;
         margin: 48px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.7; }
  h1 { font-size: 24px; }
  h2 { font-size: 17px; margin-top: 32px; }
  code, pre { background: #f5f5f5; border-radius: 6px; font-family: ui-monospace, monospace; }
  code { padding: 2px 6px; }
  pre { padding: 12px 14px; overflow-x: auto; }
  .note { background: #fff8e1; border-left: 3px solid #f0c000; padding: 10px 14px;
          border-radius: 4px; margin: 16px 0; font-size: 14px; }
</style>
</head>
<body>
<h1>群聊投资机会分析</h1>
<p>从你自己的微信高质量群聊里，用本地模型提炼潜在投资机会，整理成 Notion 情报 CRM。
   <strong>聊天数据全程留在你本机</strong>，不上云。</p>

<div class="note">
  这是一个<strong>本地工具</strong>。下面的命令都在你自己的 Mac 上跑，
  网页只负责引导。微信原始数据、密钥都不会离开你的电脑。
</div>

<h2>1. 安装</h2>
<pre>git clone &lt;本项目仓库&gt; ~/qun-alpha
cd ~/qun-alpha
python3 -m venv .venv && source .venv/bin/activate
pip install -e .</pre>

<h2>2. 解密并导出微信聊天（按引导执行）</h2>
<pre>qun-alpha decrypt-guide</pre>
<p>它会打印 macOS 上提取密钥 → 解库 → 导出的确切命令（含 sudo 的需你亲自确认）。</p>

<h2>3. 配置 Notion（可选，要写表才需要）</h2>
<pre>cp config.example.json config.json   # 填 notion_token
qun-alpha init-notion                 # 自动建三张表并打印 id</pre>

<h2>4. 起本地操作台</h2>
<pre>qun-alpha serve                       # 浏览器开 http://127.0.0.1:7800</pre>
<p>选群 → 时间范围 → 开始 → 看进度 → 结果写进 Notion。</p>

<div class="note">免责：仅用于分析<strong>你自己的</strong>微信数据，请遵守相关法律法规。</div>
</body>
</html>
```

- [ ] **Step 2: 创建 `landing/README.md`**

```markdown
# Railway 落地页（静态）

纯静态引导页，模式 X 的线上入口。本地工具的真实 UI 在用户机器的 `qun-alpha serve`（localhost），此页只负责引导安装与跑通。

## 部署到 Railway（静态）

1. 新建 Railway 项目，指向本仓库。
2. 用任意静态服务器托管 `landing/` 目录，例如设置启动命令：
   ```
   npx serve landing -l $PORT
   ```
   或用 Railway 的 Static Site 模板，root 设为 `landing/`。
3. 此页不含后端、不接触任何微信数据。

> 后续若做模式 Y（线上操作台远程驱动本地 agent），再在此基础上加鉴权与本地 agent 配对。
```

- [ ] **Step 3: 确认全套测试仍绿（落地页是静态文件，不影响测试）**

Run: `.venv/bin/pytest -q`
Expected: 约 59 passed

- [ ] **Step 4: Commit**

```bash
git add landing/
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: Railway 静态落地引导页"
```

---

## 完成标准（Plan 3b）

- [ ] `pytest -q` 全绿（约 59 passed）
- [ ] `macos_steps` 步骤顺序正确、路径正确插入、末尾接 import-export
- [ ] `classify_error` 把常见报错翻人话、未知错误原样带出
- [ ] `qun-alpha decrypt-guide` 打印步骤
- [ ] `landing/index.html` 静态落地页就绪

## 全项目收尾后的端到端验收（用户自测）

1. `qun-alpha decrypt-guide` → 按提示在 Mac 上 sudo/codesign/解密/导出
2. `qun-alpha import-export --src-dir <导出目录> --out-path exported_chats/all.json --groups-only`
3. `qun-alpha init-notion`（填好 token）
4. `qun-alpha serve` → 选群 → 真 `claude -p` 抽取 → 写 Notion 三表
