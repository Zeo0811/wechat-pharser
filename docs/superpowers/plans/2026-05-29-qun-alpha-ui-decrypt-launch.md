# Spec C UI 解密启动入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 操作台直接点按钮跑真实解密导出（① 一次性重签名 / ② 日常解密导出），需 root 的步骤用 osascript 原生管理员授权弹窗，不用粘命令；②完成后自动加载群。

**Architecture:** `decrypt_service` 加纯函数构造命令序列（osascript 管理员封装）+ `run_sequence` 按序跑、每步 emit 进度、失败带 `classify_error`。web 加 `POST /api/codesign`、`POST /api/decrypt-export`，复用 JobManager + SSE。命令固定拼装，仅 config 路径注入，不接受网页传任意命令。

**Tech Stack:** Python（subprocess/osascript）、FastAPI、原生 JS、pytest。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/config.py            # 改：加 wechat_decrypt_repo / raw_export_dir / export_path
config.example.json            # 改：加三字段
qun_alpha/decrypt_service.py   # 改：admin_applescript / codesign_steps / decrypt_export_steps / default_runner / run_sequence
qun_alpha/web.py               # 改：/api/codesign、/api/decrypt-export 端点 + create_app 注入 decrypt_runner/config_loader
qun_alpha/static/index.html    # 改：加"解密微信"卡片(两按钮) + JS 复用进度/SSE + ②后自动加载群
tests/test_config.py / test_decrypt_service.py / test_web.py  # 改
```

---

## Task 1: config 加解密路径字段

**Files:** Modify `qun_alpha/config.py`, `config.example.json`; Test `tests/test_config.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_config.py` 末尾**

```python
def test_decrypt_path_defaults(tmp_path):
    import json
    from qun_alpha.config import load_config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.wechat_decrypt_repo.endswith("ylytdeng-wechat-decrypt")
    assert cfg.raw_export_dir == "exported_chats/raw"
    assert cfg.export_path == "exported_chats/all.json"
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_config.py::test_decrypt_path_defaults -q` → Expected: FAIL (AttributeError)

- [ ] **Step 3: 在 `qun_alpha/config.py` 的 `Config` 类里追加三个字段**（加在 `cache_dir` 字段之后）：
```python
    wechat_decrypt_repo: str = "~/wechat-research/ylytdeng-wechat-decrypt"
    raw_export_dir: str = "exported_chats/raw"
    export_path: str = "exported_chats/all.json"
```

- [ ] **Step 4: 在 `config.example.json` 里追加三字段**（在 `cache_dir` 之后，注意 JSON 逗号）：
```json
    "wechat_decrypt_repo": "~/wechat-research/ylytdeng-wechat-decrypt",
    "raw_export_dir": "exported_chats/raw",
    "export_path": "exported_chats/all.json"
```
（确保上一行 `"cache_dir": ".qun_cache"` 后补逗号；这三行作为对象最后的键，最后一行不带逗号）

- [ ] **Step 5: 运行确认通过**
Run: `.venv/bin/pytest tests/test_config.py -q` → Expected: 全过（原 2 + 新 1 = 3）

- [ ] **Step 6: Commit**
```bash
git add qun_alpha/config.py config.example.json tests/test_config.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: config 加解密相关路径字段"
```

---

## Task 2: decrypt_service 命令序列 + run_sequence

**Files:** Modify `qun_alpha/decrypt_service.py`; Test `tests/test_decrypt_service.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_decrypt_service.py` 末尾**

```python
from qun_alpha.decrypt_service import (
    admin_applescript, codesign_steps, decrypt_export_steps, run_sequence,
)


def test_admin_applescript_wraps_and_escapes():
    s = admin_applescript('codesign --sign - "/Applications/WeChat.app"')
    assert "with administrator privileges" in s
    assert s.startswith("do shell script ")
    assert '\\"' in s          # 双引号被转义


def test_codesign_steps_sequence():
    steps = codesign_steps()
    assert [s["desc"] for s in steps]            # 每步有说明
    assert any("killall WeChat" in " ".join(s["argv"]) for s in steps)
    assert any("administrator privileges" in " ".join(s["argv"]) for s in steps)


def test_decrypt_export_steps_paths_and_order():
    steps = decrypt_export_steps(repo_dir="/R", raw_out="/O", export_path="/E.json")
    joined = ["".join(s["argv"]) for s in steps]
    blob = "\n".join(joined)
    assert "/R/find_all_keys_macos.c" in blob          # 编译
    assert "administrator privileges" in blob          # 提密钥需 root
    assert "decrypt_db.py" in blob
    assert "export_all_chats.py /O" in blob
    assert "import-export" in blob and "/E.json" in blob
    # 顺序：编译 < 提密钥 < 解库 < 导出 < 转格式
    idx = lambda kw: next(i for i, b in enumerate(joined) if kw in b)
    assert idx("find_all_keys_macos.c") < idx("administrator privileges") \
           < idx("decrypt_db.py") < idx("export_all_chats.py") < idx("import-export")


def test_run_sequence_runs_all_and_emits():
    events = []
    calls = []
    runner = lambda argv: (calls.append(argv) or (0, ""))
    steps = [{"desc": "a", "argv": ["x"]}, {"desc": "b", "argv": ["y"]}]
    out = run_sequence(steps, runner=runner, emit=events.append)
    assert out["steps"] == 2
    assert len(calls) == 2
    assert [e["current"] for e in events] == [1, 2]
    assert events[0]["total"] == 2 and events[0]["message"] == "a"


def test_run_sequence_stops_on_failure_with_hint():
    import pytest
    calls = []

    def runner(argv):
        calls.append(argv)
        return (1, "task_for_pid failed (5)")    # 第一步就失败

    steps = [{"desc": "scan", "argv": ["s"]}, {"desc": "next", "argv": ["n"]}]
    with pytest.raises(RuntimeError) as ei:
        run_sequence(steps, runner=runner, emit=lambda e: None)
    assert "重签名" in str(ei.value)            # classify_error 翻人话
    assert len(calls) == 1                       # 失败即停，不跑第二步
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_decrypt_service.py -q` → Expected: ImportError

- [ ] **Step 3: 在 `qun_alpha/decrypt_service.py` 顶部加 `import subprocess`，并在文件末尾追加：**

```python
import subprocess


def admin_applescript(shell_cmd: str) -> str:
    """把 shell 命令包成可弹 macOS 管理员授权框的 AppleScript（osascript -e 的参数）。"""
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "{escaped}" with administrator privileges'


def codesign_steps() -> list[dict]:
    """① 一次性：退出微信 + ad-hoc 重签名（需管理员）。"""
    return [
        {"desc": "退出微信", "argv": ["bash", "-lc", "killall WeChat || true"]},
        {"desc": "重签名微信（管理员）",
         "argv": ["osascript", "-e", admin_applescript(
             "codesign --force --deep --sign - /Applications/WeChat.app")]},
    ]


def decrypt_export_steps(repo_dir: str, raw_out: str, export_path: str) -> list[dict]:
    """② 提密钥→解库→导出→转格式。提密钥需管理员，其余不需。"""
    return [
        {"desc": "编译密钥扫描器",
         "argv": ["bash", "-lc",
                  f"cc -O2 -o {repo_dir}/find_all_keys_macos "
                  f"{repo_dir}/find_all_keys_macos.c -framework Foundation"]},
        {"desc": "提取数据库密钥（管理员）",
         "argv": ["osascript", "-e", admin_applescript(
             f"cd {repo_dir} && ./find_all_keys_macos")]},
        {"desc": "解密数据库",
         "argv": ["bash", "-lc", f"cd {repo_dir} && python3 decrypt_db.py"]},
        {"desc": "导出聊天记录",
         "argv": ["bash", "-lc", f"cd {repo_dir} && python3 export_all_chats.py {raw_out}"]},
        {"desc": "转换成本项目格式",
         "argv": ["bash", "-lc",
                  f"qun-alpha import-export --src-dir {raw_out} "
                  f"--out-path {export_path} --groups-only"]},
    ]


def default_runner(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    return proc.returncode, (proc.stderr or proc.stdout or "")


def run_sequence(steps: list[dict], runner=default_runner, emit=lambda e: None) -> dict:
    """按序跑每步，跑前 emit 进度；任一步非零退出即抛人话错误并停止。"""
    total = len(steps)
    for i, step in enumerate(steps):
        emit({"stage": "decrypt", "current": i + 1, "total": total,
              "message": step["desc"]})
        code, output = runner(step["argv"])
        if code != 0:
            raise RuntimeError(classify_error(output))
    return {"steps": total}
```

- [ ] **Step 4: 运行确认通过**
Run: `.venv/bin/pytest tests/test_decrypt_service.py -q` → Expected: 全过（原 4 + 新 5 = 9）

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/decrypt_service.py tests/test_decrypt_service.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: decrypt_service 命令序列(osascript管理员) + run_sequence"
```

---

## Task 3: web 解密端点

**Files:** Modify `qun_alpha/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
def test_codesign_and_decrypt_endpoints_run_steps(tmp_path):
    calls = []

    class Cfg:
        wechat_decrypt_repo = "/R"
        raw_export_dir = "/O"
        export_path = "/E.json"

    mgr = JobManager()
    app = create_app(manager=mgr,
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [],
                     decrypt_runner=lambda argv: (calls.append(argv) or (0, "")),
                     config_loader=lambda: Cfg())
    client = TestClient(app)

    r1 = client.post("/api/codesign")
    assert r1.status_code == 200
    mgr.join(r1.json()["job_id"])

    r2 = client.post("/api/decrypt-export")
    assert r2.status_code == 200
    assert r2.json()["export_path"] == "/E.json"
    mgr.join(r2.json()["job_id"])
    assert mgr.get(r2.json()["job_id"]).status == "done"
    # codesign(2步) + decrypt-export(5步) 都跑了
    assert len(calls) == 7


def test_decrypt_export_config_error_returns_400():
    def boom():
        raise FileNotFoundError("配置文件不存在")
    app = create_app(manager=JobManager(),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [],
                     config_loader=boom)
    client = TestClient(app)
    assert client.post("/api/decrypt-export").status_code == 400
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: FAIL（create_app 不认 decrypt_runner/config_loader；无端点）

- [ ] **Step 3: 修改 `qun_alpha/web.py`**

(a) 顶部 import 增加（与现有 qun_alpha import 合并一行或新增一行）：
```python
from qun_alpha import decrypt_service
```

(b) `create_app` 签名追加两个参数（带默认值）：
```python
def create_app(*, manager: Optional[JobManager] = None,
               target_factory: Optional[TargetFactory] = None,
               groups_provider: Optional[GroupsProvider] = None,
               job_store: Optional[Any] = None,
               estimator: Optional[Callable] = None,
               decrypt_runner: Optional[Callable] = None,
               config_loader: Optional[Callable] = None) -> FastAPI:
```
在函数开头（`estimator = estimator or _default_estimator` 之后）加：
```python
    decrypt_runner = decrypt_runner or decrypt_service.default_runner
    if config_loader is None:
        from qun_alpha.config import load_config
        config_loader = lambda: load_config("config.json")
```

(c) 在 `return app` 之前追加两个端点：
```python
    @app.post("/api/codesign")
    def codesign_ep():
        steps = decrypt_service.codesign_steps()
        job_id = manager.start(
            lambda emit: decrypt_service.run_sequence(steps, runner=decrypt_runner, emit=emit))
        return {"job_id": job_id}

    @app.post("/api/decrypt-export")
    def decrypt_export_ep():
        try:
            cfg = config_loader()
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        import os
        repo = os.path.expanduser(cfg.wechat_decrypt_repo)
        steps = decrypt_service.decrypt_export_steps(repo, cfg.raw_export_dir, cfg.export_path)
        job_id = manager.start(
            lambda emit: decrypt_service.run_sequence(steps, runner=decrypt_runner, emit=emit))
        return {"job_id": job_id, "export_path": cfg.export_path}
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过（+2）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web /api/codesign + /api/decrypt-export 端点"
```

---

## Task 4: 操作台"解密微信"卡片

**Files:** Modify `qun_alpha/static/index.html`; Test `tests/test_web.py`

- [ ] **Step 1: 追加 smoke 测试到 `tests/test_web.py` 末尾**

```python
def test_index_has_decrypt_card():
    client = _client(JobManager())
    html = client.get("/").text
    assert 'id="codesignBtn"' in html
    assert 'id="decryptBtn"' in html
    assert "解密微信" in html
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_index_has_decrypt_card -q` → Expected: FAIL

- [ ] **Step 3: 在 `qun_alpha/static/index.html` 里，找到导出路径那张卡片（含 `id="export_path"` 的 `<div class="card">`），在它【之后】插入这张新卡片：**

找到这段（导出路径卡片的结束 `</div>`，紧接着是 `<div class="card" id="groupsCard"`）。在 `<div class="card" id="groupsCard" style="display:none">` 这一行【之前】插入：
```html
<div class="card">
  <label>解密微信（首次设置签名后，日常只点②）</label>
  <div class="row" style="margin-top:10px">
    <button id="codesignBtn" class="ghost">① 重签名（首次）</button>
    <button id="decryptBtn">② 解密并导出</button>
  </div>
  <div class="muted" style="margin-top:8px">①会退出微信并弹管理员密码框；之后请重开并登录微信，再点②。②需微信开着且已登录。</div>
</div>

```

- [ ] **Step 4: 在 `<script>` 内，`$("start").onclick` 定义【之前】插入一个复用进度流的 helper 和两个按钮处理：**

找到 `const selectedGroups=()=>` 这一行，在它【之后】插入：
```javascript
function streamJob(job_id, onDone){
  $("log").textContent="";$("result").className="";$("result").textContent="";
  $("barfill").style.width="0";$("barfill").classList.add("pulse");
  const src=new EventSource("/api/jobs/"+job_id+"/stream");
  src.onmessage=(e)=>{
    const d=JSON.parse(e.data);
    if(d.stage!==undefined&&d.total!==undefined){
      const pct=d.total?Math.round(d.current/d.total*100):100;
      $("barfill").style.width=pct+"%";
      $("log").textContent+=`[${d.stage}] ${d.message}\n`;$("log").scrollTop=$("log").scrollHeight;
    }
    if(d.status){
      src.close();$("barfill").classList.remove("pulse");
      if(d.status==="error"){$("result").textContent="出错："+d.error;$("result").className="show";}
      else{$("result").className="show";if(onDone)onDone(d);}
    }
  };
}

async function postJob(url){
  const res=await fetch(url,{method:"POST"});
  const body=await res.json();
  if(!res.ok){$("result").textContent="失败："+(body.error||res.status);$("result").className="show";return null;}
  return body;
}

$("codesignBtn").onclick=async()=>{
  const b=await postJob("/api/codesign");
  if(b)streamJob(b.job_id,()=>{$("result").textContent="重签名完成，请重新打开并登录微信，再点②。";});
};

$("decryptBtn").onclick=async()=>{
  const b=await postJob("/api/decrypt-export");
  if(b)streamJob(b.job_id,()=>{$("result").textContent="解密导出完成，正在加载群…";$("loadGroups").click();});
};
```

- [ ] **Step 5: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过（+1）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 6: Commit**
```bash
git add qun_alpha/static/index.html tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: 操作台解密微信卡片(①重签名 ②解密导出, ②后自动加载群)"
```

---

## 完成标准（Spec C）
- [ ] `pytest -q` 全绿
- [ ] config 有 wechat_decrypt_repo/raw_export_dir/export_path
- [ ] decrypt_service：osascript 管理员封装、codesign/decrypt-export 序列、run_sequence 按序+失败即停+人话
- [ ] web：/api/codesign、/api/decrypt-export（config 错误 400）
- [ ] 操作台有①②按钮，②完成自动加载群
- [ ] 既有测试不回归

## 手动验收（用户，真机）
`qun-alpha serve` → 点①弹管理员密码框重签名 → 重开登录微信 → 点② 弹一次密码 → 看进度 → 群自动加载 → 选群分析。
