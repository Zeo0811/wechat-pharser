# Spec A 模型后端可选（Claude/Codex）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把写死的 `claude -p` 抽象成可切换 runner（claude / codex），config 记选择，鲁棒解析两种 CLI 输出，加 `qun-alpha model` 命令与 `analyze --model`。

**Architecture:** 新增 `runners.py`（claude_runner / codex_runner / get_runner / detect_available，subprocess 注入便于测）；extractor 的 `default_claude_runner` 改为 runners.claude_runner 别名、`_parse` 改鲁棒（抓最外层 `[...]`）；config 加 `model_backend`；cli 加 `model` 命令 + `analyze --model`；web 用 `get_runner(cfg.model_backend)`。

**Tech Stack:** Python（subprocess/shutil，stdlib）、pydantic、typer、pytest。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/runners.py     # 新：BACKENDS / claude_runner / codex_runner / get_runner / detect_available
qun_alpha/extractor.py   # 改：default_claude_runner→runners.claude_runner；_parse 鲁棒
qun_alpha/config.py      # 改：加 model_backend
qun_alpha/cli.py         # 改：model 命令 + analyze --model + analyze 用 get_runner
qun_alpha/web.py         # 改：_default_target_factory 用 get_runner(cfg.model_backend)
tests/test_runners.py / test_extractor.py / test_config.py / test_cli_model.py（新/改）
```

---

## Task 1: runners.py（后端抽象 + 检测）

**Files:** Create `qun_alpha/runners.py`; Test `tests/test_runners.py`

- [ ] **Step 1: 写失败测试 `tests/test_runners.py`**

```python
import pytest
from qun_alpha import runners


def test_claude_runner_builds_cmd():
    calls = []
    out = runners.claude_runner("PROMPT", run=lambda argv: calls.append(argv) or "OUT")
    assert calls[0] == ["claude", "-p", "PROMPT"]
    assert out == "OUT"


def test_codex_runner_builds_cmd():
    calls = []
    out = runners.codex_runner("PROMPT", run=lambda argv: calls.append(argv) or "OUT")
    assert calls[0] == ["codex", "exec", "PROMPT"]
    assert out == "OUT"


def test_get_runner_routes():
    assert runners.get_runner("claude") is runners.claude_runner
    assert runners.get_runner("codex") is runners.codex_runner
    with pytest.raises(ValueError):
        runners.get_runner("gpt99")


def test_detect_available(monkeypatch):
    monkeypatch.setattr(runners.shutil, "which",
                        lambda b: "/usr/bin/" + b if b == "codex" else None)
    assert runners.detect_available() == ["codex"]


def test_get_runner_callable_with_prompt_only():
    # get_runner 返回的函数能只用 (prompt) 调用（extract_chunk 这么用）；
    # 用 run= 注入验证，不真跑 CLI
    r = runners.get_runner("claude")
    assert r("hi", run=lambda argv: "X") == "X"
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_runners.py -q` → Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 `qun_alpha/runners.py`**

```python
from __future__ import annotations
import shutil
import subprocess
from typing import Callable

BACKENDS = ["claude", "codex"]


def _run(argv: list[str]) -> str:
    """默认执行器：跑 CLI，返回 stdout。"""
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return proc.stdout or ""


def claude_runner(prompt: str, run: Callable[[list], str] = _run) -> str:
    return run(["claude", "-p", prompt])


def codex_runner(prompt: str, run: Callable[[list], str] = _run) -> str:
    return run(["codex", "exec", prompt])


def get_runner(backend: str) -> Callable[[str], str]:
    if backend == "claude":
        return claude_runner
    if backend == "codex":
        return codex_runner
    raise ValueError(f"未知模型后端：{backend}（支持 {BACKENDS}）")


def detect_available() -> list[str]:
    """返回当前 PATH 上可用的后端 CLI。"""
    return [b for b in BACKENDS if shutil.which(b)]
```

注意：`get_runner` 返回的函数有默认参数 `run=_run`，故 `r(prompt)` 单参可调用（满足 extract_chunk 的 `runner(prompt)` 用法），也可 `r(prompt, run=fake)` 注入测试。

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_runners.py -q` → Expected: 5 passed

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/runners.py tests/test_runners.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: runners 模型后端抽象(claude/codex)+检测"
```

---

## Task 2: extractor 鲁棒解析 + runner 委托

**Files:** Modify `qun_alpha/extractor.py`; Test `tests/test_extractor.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_extractor.py` 末尾**

```python
from qun_alpha.extractor import _parse


def test_parse_tolerates_preamble_and_trailing():
    noisy = ('我帮你分析了一下，结果如下：\n'
             '[{"kind":"company","name":"X","source":{"group_name":"g","sender":"s",'
             '"timestamp":1,"msg_id":"m"}}]\n以上就是全部。')
    out = _parse(noisy)
    assert out is not None and len(out) == 1 and out[0].name == "X"


def test_parse_pure_json_still_works():
    pure = '[{"kind":"company","name":"Y","source":{"group_name":"g","sender":"s","timestamp":1,"msg_id":"m"}}]'
    out = _parse(pure)
    assert out and out[0].name == "Y"


def test_parse_garbage_returns_none():
    assert _parse("完全没有 JSON 的一段话") is None


def test_default_claude_runner_is_claude_backend():
    from qun_alpha import extractor, runners
    assert extractor.default_claude_runner is runners.claude_runner
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_extractor.py -q`
Expected: FAIL（鲁棒解析未实现 / default_claude_runner 还是旧 def）

- [ ] **Step 3: 修改 `qun_alpha/extractor.py`**

(a) 顶部 import：把
```python
import json
import os
import subprocess
from typing import Callable, Optional
from pydantic import TypeAdapter, ValidationError
from qun_alpha.models import MessageChunk, RawEntity
```
改为（去掉 subprocess，加 runners）：
```python
import json
import os
from typing import Callable, Optional
from pydantic import TypeAdapter, ValidationError
from qun_alpha.models import MessageChunk, RawEntity
from qun_alpha import runners
```

(b) 把现有 `default_claude_runner` 整个函数（`def default_claude_runner(prompt): ...` 含 subprocess 那几行）替换为一行别名：
```python
# 默认后端 = Claude（保留原名以兼容现有调用）
default_claude_runner = runners.claude_runner
```

(c) 把 `_parse` 替换为鲁棒版（先整段，再抓最外层数组）：
```python
def _extract_json_array(text: str):
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        pass
    i, j = t.find("["), t.rfind("]")
    if i != -1 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _parse(text: str) -> Optional[list[RawEntity]]:
    data = _extract_json_array(text)
    if data is None:
        return None
    try:
        return _ADAPTER.validate_python(data)
    except (ValidationError, ValueError):
        return None
```

注意：`default_claude_runner = runners.claude_runner` 必须定义在 `extract_chunk` 之前（它的默认参数引用它）。原 def 也在前面，直接原位替换即可。

- [ ] **Step 4: 运行确认通过 + 全套无回归**
Run: `.venv/bin/pytest tests/test_extractor.py -q` → Expected: 全过（原 4 + 新 4 = 8）
Run: `.venv/bin/pytest -q` → Expected: 全绿（extract_chunk 默认 runner 仍可用）

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/extractor.py tests/test_extractor.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: extractor 鲁棒JSON解析 + default runner 委托 runners.claude"
```

---

## Task 3: config 加 model_backend

**Files:** Modify `qun_alpha/config.py`, `config.example.json`; Test `tests/test_config.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_config.py` 末尾**

```python
def test_model_backend_default(tmp_path):
    import json
    from qun_alpha.config import load_config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}), encoding="utf-8")
    assert load_config(str(p)).model_backend == "claude"


def test_model_backend_override(tmp_path):
    import json
    from qun_alpha.config import load_config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_backend": "codex"}), encoding="utf-8")
    assert load_config(str(p)).model_backend == "codex"
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_config.py::test_model_backend_default -q` → Expected: FAIL (AttributeError)

- [ ] **Step 3: 在 `qun_alpha/config.py` 的 `Config` 类加字段**（紧跟 `export_path` 之后）：
```python
    model_backend: str = "claude"   # claude | codex
```

- [ ] **Step 4: 在 `config.example.json` 加一行**（在最后一个键后补逗号，新增）：
```json
    "model_backend": "claude"
```
（即把上一行末尾补逗号，再加这行作为新的最后一个键，闭合 `}`。）

- [ ] **Step 5: 运行确认通过**
Run: `.venv/bin/pytest tests/test_config.py -q` → Expected: 全过
验证 JSON 合法：`.venv/bin/python -c "import json;json.load(open('config.example.json'))"`

- [ ] **Step 6: Commit**
```bash
git add qun_alpha/config.py config.example.json tests/test_config.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: config 加 model_backend 字段"
```

---

## Task 4: cli model 命令 + analyze --model + web 用 get_runner

**Files:** Modify `qun_alpha/cli.py`, `qun_alpha/web.py`; Test `tests/test_cli_model.py`

- [ ] **Step 1: 写失败测试 `tests/test_cli_model.py`**

```python
import json
from qun_alpha.cli import model_status


def test_model_status_shows_available_and_current(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude", "codex"])
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_backend": "codex"}), encoding="utf-8")
    info = model_status(config_path=str(p))
    assert info["available"] == ["claude", "codex"]
    assert info["current"] == "codex"


def test_model_status_set_writes_config(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude"])
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model_backend": "claude"}), encoding="utf-8")
    info = model_status(config_path=str(p), set_backend="codex")
    assert info["current"] == "codex"
    assert json.loads(p.read_text())["model_backend"] == "codex"


def test_model_status_default_when_no_config(tmp_path, monkeypatch):
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: [])
    info = model_status(config_path=str(tmp_path / "nope.json"))
    assert info["current"] == "claude"


def test_model_status_rejects_unknown(tmp_path, monkeypatch):
    import pytest
    from qun_alpha import runners
    monkeypatch.setattr(runners, "detect_available", lambda: ["claude"])
    with pytest.raises(ValueError):
        model_status(config_path=str(tmp_path / "c.json"), set_backend="gpt99")
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_cli_model.py -q` → Expected: ImportError (model_status)

- [ ] **Step 3: 修改 `qun_alpha/cli.py`**

(a) 顶部 import 增加 runners：把
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service
```
改为
```python
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service, runners
```

(b) 在 `if __name__ == "__main__":` 之前追加 `model_status` helper + `model` 命令：
```python
def model_status(config_path: str = "config.json", set_backend: str | None = None) -> dict:
    import os
    available = runners.detect_available()
    if set_backend is not None:
        if set_backend not in runners.BACKENDS:
            raise ValueError(f"未知后端：{set_backend}（支持 {runners.BACKENDS}）")
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["model_backend"] = set_backend
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return {"available": available, "current": set_backend}
    current = "claude"
    if os.path.exists(config_path):
        from qun_alpha.config import load_config
        current = load_config(config_path).model_backend
    return {"available": available, "current": current}


@app.command()
def model(set: str = typer.Option(None, "--set", help="切换后端: claude / codex"),
          config_path: str = typer.Option("config.json")):
    """查看/切换模型后端（claude / codex）。"""
    info = model_status(config_path=config_path, set_backend=set)
    typer.echo(f"可用后端: {', '.join(info['available']) or '(未检测到 claude/codex)'}")
    typer.echo(f"当前后端: {info['current']}")
```
（cli.py 顶部已 `import json`？若没有，在文件顶部加 `import json`。）

(c) 修改 `analyze` 命令：增加 `--model` 选项，并把 runner 由写死改成按后端取。
在 analyze 的参数里加：
```python
    model: str = typer.Option(None, "--model", help="本次用哪个后端: claude / codex"),
```
把 analyze 里 `runner=extractor.default_claude_runner,` 改为：
```python
        runner=runners.get_runner(model or cfg.model_backend),
```

- [ ] **Step 4: 修改 `qun_alpha/web.py`** 的 `_default_target_factory`

顶部 import 增加 runners（与现有 `from qun_alpha import ...` 合并）：把
```python
from qun_alpha import chat_reader, orchestrator, extractor, estimate as estimate_mod, decrypt_service
```
改为
```python
from qun_alpha import chat_reader, orchestrator, extractor, estimate as estimate_mod, decrypt_service, runners
```
把 `_default_target_factory` 里
```python
            runner=extractor.default_claude_runner,
```
改为
```python
            runner=runners.get_runner(params.get("model") or cfg.model_backend),
```

- [ ] **Step 5: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_cli_model.py -q` → Expected: 4 passed
Run: `.venv/bin/pytest -q` → Expected: 全绿
验证命令存在：`.venv/bin/python -c "from qun_alpha.cli import app, model_status; print('ok')"`

- [ ] **Step 6: Commit**
```bash
git add qun_alpha/cli.py qun_alpha/web.py tests/test_cli_model.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: cli model 命令 + analyze --model + web 用 get_runner"
```

---

## 完成标准（Spec A）
- [ ] `pytest -q` 全绿
- [ ] `runners`：claude/codex 命令构造、get_runner 路由、detect_available 检测
- [ ] extractor `_parse` 容忍前后噪声、`default_claude_runner` 即 runners.claude_runner
- [ ] config 有 model_backend（默认 claude）
- [ ] `qun-alpha model [--set codex]` 可看/切；`analyze --model`；web 按 cfg.model_backend 选 runner

## 后续（不在 A）
- B 安装器：检测/引导安装 codex + 首次选后端写 config。
- C 网页：模型选择下拉（调 detect_available + 写 config）。
