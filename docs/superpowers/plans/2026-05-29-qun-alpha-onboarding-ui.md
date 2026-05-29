# Spec B 引导门户 + UI 重做 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 Spec A 的预估/增量/resume 接进 Web 接口，并把本地操作台 + onboarding 引导页按 Catppuccin 等宽双主题 mockup 重做（含装 wechat-decrypt 包的手把手向导）。

**Architecture:** Task 1 给 `web.create_app` 加 estimate/resume/jobs 端点 + incremental 透传，依赖注入便于 TestClient 测。Task 2/3 是纯前端（HTML/CSS/JS），各自内联同一套 Catppuccin 设计 token，以 smoke 测 + 用户视觉验收为准。

**Tech Stack:** FastAPI/httpx(TestClient)、原生 JS（fetch/EventSource）、pytest。`.venv` + `.venv/bin/pytest`。

---

## File Structure
```
qun_alpha/web.py            # 改：estimate/resume/jobs 端点 + _default_target_factory 加 incremental
qun_alpha/static/index.html # 重做：Catppuccin 双主题 + 动画 + 预估面板 + 增量开关
landing/index.html          # 重做：Catppuccin 双主题 onboarding 向导（含装 wechat-decrypt 包）
.gitignore                  # 加 .qun_jobs/ .qun_state/
tests/test_web.py           # 改：加 estimate/resume/jobs 端点测试 + 重做后 smoke
```

---

## Task 1: web 接入 estimate / incremental / resume / jobs

**Files:** Modify `qun_alpha/web.py`, `.gitignore`; Test `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
from qun_alpha.job_store import JobStore


def test_estimate_endpoint():
    app = create_app(manager=JobManager(),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [],
                     estimator=lambda ep, gids, s, en: {"chunks": 5, "to_run": 5,
                                                        "est_minutes": 1.0})
    client = TestClient(app)
    r = client.get("/api/estimate", params={"export_path": "x.json", "groups": "g1,g2"})
    assert r.status_code == 200
    assert r.json()["chunks"] == 5


def test_jobs_list_endpoint(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    store.create("j1", {"group_ids": ["g1"]})
    app = create_app(manager=JobManager(job_store=store),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [], job_store=store)
    client = TestClient(app)
    assert any(j["job_id"] == "j1" for j in client.get("/api/jobs").json())


def test_resume_endpoint(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    mgr = JobManager(job_store=store)
    runs = []

    def tf(params):
        def target(emit):
            runs.append(1)
            return {"ok": True}
        return target

    app = create_app(manager=mgr, target_factory=tf,
                     groups_provider=lambda e: [], job_store=store)
    client = TestClient(app)
    jid = client.post("/api/jobs", json={"export_path": "x",
                                         "group_ids": ["g1"]}).json()["job_id"]
    mgr.join(jid)
    r = client.post(f"/api/jobs/{jid}/resume")
    assert r.status_code == 200
    mgr.join(r.json()["job_id"])
    assert len(runs) == 2


def test_resume_unknown_returns_400(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    app = create_app(manager=JobManager(job_store=store),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [], job_store=store)
    client = TestClient(app)
    assert client.post("/api/jobs/nope/resume").status_code == 400
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: FAIL（create_app 不认 estimator/job_store；无 /api/estimate、/api/jobs、resume 路由）

- [ ] **Step 3: 修改 `qun_alpha/web.py`**

(a) 顶部 import 增加：
```python
from qun_alpha import chat_reader, orchestrator, extractor, estimate as estimate_mod
from qun_alpha.cursor_store import CursorStore
from qun_alpha.job_store import JobStore
```
（若已有 `from qun_alpha import chat_reader` 行，改成上面这行合并；其余 import 保留）

(b) 把 `_default_target_factory` 整个替换为（加 incremental + cursor_store + concurrency）：
```python
def _default_target_factory(params: dict):
    from qun_alpha.config import load_config
    cfg = load_config(params.get("config_path", "config.json"))
    dry_run = params.get("dry_run", True)
    incremental = params.get("incremental", False)
    concurrency = int(params.get("concurrency", 3))
    client = None
    if not dry_run:
        from notion_client import Client
        client = Client(auth=cfg.notion_token)
    cursor = CursorStore()

    def target(emit):
        return orchestrator.run_job(
            export_path=params["export_path"],
            group_ids=params["group_ids"],
            start=params.get("start", 0),
            end=params.get("end", 2_000_000_000),
            max_messages=cfg.max_messages_per_chunk,
            prompt_version=cfg.prompt_version,
            runner=extractor.default_claude_runner,
            cache_dir=cfg.cache_dir,
            notion_client=client,
            companies_db_id=cfg.notion_companies_db_id,
            people_db_id=cfg.notion_people_db_id,
            links_db_id=cfg.notion_links_db_id,
            dry_run=dry_run, emit=emit,
            concurrency=concurrency,
            incremental=incremental, cursor_store=cursor,
        )
    return target


def _default_estimator(export_path: str, group_ids: list, start: int, end: int) -> dict:
    from qun_alpha.config import load_config
    cfg = load_config("config.json")
    return estimate_mod.estimate_run(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=cfg.max_messages_per_chunk, prompt_version=cfg.prompt_version,
        cache_dir=cfg.cache_dir)
```

(c) 把 `create_app` 的签名与开头改为（加 job_store/estimator，注入便于测）：
```python
def create_app(*, manager: Optional[JobManager] = None,
               target_factory: Optional[TargetFactory] = None,
               groups_provider: Optional[GroupsProvider] = None,
               job_store: Optional[Any] = None,
               estimator: Optional[Callable] = None) -> FastAPI:
    if manager is None:
        job_store = job_store or JobStore()
        manager = JobManager(job_store=job_store)
    target_factory = target_factory or _default_target_factory
    groups_provider = groups_provider or chat_reader.list_groups
    estimator = estimator or _default_estimator
    app = FastAPI(title="群聊投资机会分析")
```
（注意顶部需要 `from typing import Any, Callable, Optional`；若缺 Callable 则补）

(d) 在 `create_app` 内、`return app` 之前，新增三个端点：
```python
    @app.get("/api/estimate")
    def estimate_ep(export_path: str, groups: str, start: int = 0,
                    end: int = 2_000_000_000):
        gids = [g.strip() for g in groups.split(",") if g.strip()]
        return estimator(export_path, gids, start, end)

    @app.get("/api/jobs")
    def jobs_ep():
        return job_store.list() if job_store is not None else []

    @app.post("/api/jobs/{job_id}/resume")
    def resume_ep(job_id: str):
        try:
            new_id = manager.resume(job_id, target_factory)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"job_id": new_id}
```

- [ ] **Step 4: `.gitignore` 追加两行**
```
.qun_jobs/
.qun_state/
```

- [ ] **Step 5: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 通过（原 9 + 新 4 = 13）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 6: Commit**
```bash
git add qun_alpha/web.py tests/test_web.py .gitignore
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web 接入 estimate/jobs/resume 端点 + incremental 透传"
```

---

## Task 2: 操作台 UI 重做（Catppuccin 双主题 + 预估 + 增量）

**Files:** Modify `qun_alpha/static/index.html`; Test `tests/test_web.py`

- [ ] **Step 1: 追加 smoke 测试到 `tests/test_web.py` 末尾**

```python
def test_index_has_redesign_elements():
    client = _client(JobManager())
    html = client.get("/").text
    assert 'id="themeToggle"' in html        # 主题切换
    assert 'id="estimate"' in html           # 预估面板
    assert 'id="incremental"' in html        # 增量开关
    assert "--accent" in html                # Catppuccin token
    assert 'id="groups"' in html and 'id="start"' in html
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_index_has_redesign_elements -q` → Expected: FAIL（旧页面无这些元素）

- [ ] **Step 3: 用下面内容整体替换 `qun_alpha/static/index.html`**

```html
<!doctype html>
<html lang="zh" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊投资机会分析</title>
<style>
  /* === Catppuccin 设计 token（与 landing 同步）=== */
  html[data-theme="light"]{--base:#eff1f5;--mantle:#e6e9ef;--text:#4c4f69;--subtext:#6c6f85;
    --surface0:#ccd0da;--surface1:#bcc0cc;--accent:#8839ef;--green:#40a02b;--red:#d20f39;
    --shadow:0 4px 12px rgba(76,79,105,.08),0 8px 24px rgba(76,79,105,.10);}
  html[data-theme="dark"]{--base:#1e1e2e;--mantle:#181825;--text:#cdd6f4;--subtext:#a6adc8;
    --surface0:#313244;--surface1:#45475a;--accent:#cba6f7;--green:#a6e3a1;--red:#f38ba8;
    --shadow:0 4px 16px rgba(0,0,0,.30),0 8px 32px rgba(0,0,0,.40);}
  *{box-sizing:border-box}
  body{font-family:'Maple Mono NF CN','JetBrains Mono','SF Mono',Consolas,monospace;
    background:var(--mantle);color:var(--text);max-width:760px;margin:0 auto;padding:32px 20px;
    line-height:1.6;transition:background .3s,color .3s;}
  h1{font-size:20px;display:flex;align-items:center;justify-content:space-between}
  .card{background:var(--base);border-radius:12px;padding:18px 20px;margin:14px 0;box-shadow:var(--shadow)}
  label{font-size:13px;color:var(--subtext)}
  input[type=text]{width:100%;padding:9px 11px;margin-top:6px;border:1px solid var(--surface0);
    border-radius:8px;background:var(--mantle);color:var(--text);font-family:inherit}
  button{padding:9px 16px;border:none;border-radius:8px;background:var(--accent);color:var(--base);
    font-family:inherit;font-weight:600;cursor:pointer;transition:transform .1s,opacity .2s}
  button:hover{opacity:.9}button:active{transform:translateY(1px)}
  button.ghost{background:transparent;color:var(--text);border:1px solid var(--surface0)}
  #themeToggle{background:transparent;color:var(--text);font-size:18px;border:none;padding:4px 8px}
  #groups label{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:8px;
    color:var(--text);cursor:pointer;transition:background .15s}
  #groups label:hover{background:var(--surface0)}
  #estimate{font-size:13px;color:var(--subtext);min-height:18px}
  #bar{height:10px;background:var(--surface0);border-radius:5px;overflow:hidden;margin-top:6px}
  #barfill{height:100%;width:0;background:var(--accent);transition:width .25s ease}
  #barfill.pulse{animation:pulse 1.1s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.55}}
  #log{font-size:12.5px;color:var(--subtext);white-space:pre-wrap;margin-top:10px;max-height:200px;overflow:auto}
  #result{margin-top:12px;font-weight:600;opacity:0;transition:opacity .4s}
  #result.show{opacity:1}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--subtext);font-size:12px}
</style>
</head>
<body>
<h1>群聊投资机会分析 <button id="themeToggle" title="切换主题">◐</button></h1>

<div class="card">
  <label>导出 JSON 路径</label>
  <input type="text" id="export_path" placeholder="exported_chats/all.json" value="exported_chats/sample.json">
  <div class="row" style="margin-top:10px">
    <button id="loadGroups">加载群列表</button>
    <span class="muted">先加载，再勾选要分析的群</span>
  </div>
</div>

<div class="card" id="groupsCard" style="display:none">
  <label>选择群</label>
  <div id="groups"></div>
</div>

<div class="card">
  <div class="row">
    <label><input type="checkbox" id="incremental"> 增量（只分析上次之后的新消息）</label>
    <label><input type="checkbox" id="dry_run" checked> 预演（不写 Notion）</label>
  </div>
  <div class="row" style="margin-top:12px">
    <button id="estimateBtn" class="ghost">预估</button>
    <button id="start">开始分析</button>
  </div>
  <div id="estimate" style="margin-top:10px"></div>
</div>

<div class="card">
  <div id="bar"><div id="barfill"></div></div>
  <div id="log"></div>
  <div id="result"></div>
</div>

<script>
const $=(id)=>document.getElementById(id);

// 主题：localStorage 记忆
const savedTheme=localStorage.getItem("qa-theme")||"light";
document.documentElement.setAttribute("data-theme",savedTheme);
$("themeToggle").onclick=()=>{
  const t=document.documentElement.getAttribute("data-theme")==="light"?"dark":"light";
  document.documentElement.setAttribute("data-theme",t);
  localStorage.setItem("qa-theme",t);
};

const selectedGroups=()=>[...document.querySelectorAll(".grp:checked")].map(e=>e.value);

$("loadGroups").onclick=async()=>{
  const ep=$("export_path").value.trim();
  try{
    const res=await fetch("/api/groups?export_path="+encodeURIComponent(ep));
    if(!res.ok){$("result").textContent="加载群失败："+res.status;$("result").className="show";return;}
    const groups=await res.json();
    $("groups").innerHTML=groups.map(g=>
      `<label><input type="checkbox" class="grp" value="${g.group_id}"> ${g.group_name} <span class="muted">(${g.count})</span></label>`).join("");
    $("groupsCard").style.display="block";
  }catch(err){$("result").textContent="请求出错："+err;$("result").className="show";}
};

$("estimateBtn").onclick=async()=>{
  const gids=selectedGroups();
  if(!gids.length){$("estimate").textContent="请先勾选群再预估。";return;}
  $("estimate").textContent="预估中…";
  try{
    const q=new URLSearchParams({export_path:$("export_path").value.trim(),groups:gids.join(",")});
    const res=await fetch("/api/estimate?"+q);
    const d=await res.json();
    if(!res.ok){$("estimate").textContent="预估失败："+(d.error||res.status);return;}
    $("estimate").textContent=`约 ${d.chunks} 块（已缓存 ${d.cached??0}，待跑 ${d.to_run}）· 预计 ~${d.est_minutes} 分钟 · 粗估 $${d.est_cost_usd}`;
  }catch(err){$("estimate").textContent="预估出错："+err;}
};

$("start").onclick=async()=>{
  const group_ids=selectedGroups();
  $("log").textContent="";$("result").className="";$("result").textContent="";
  $("barfill").style.width="0";
  if(!group_ids.length){$("result").textContent="请先加载并勾选至少一个群。";$("result").className="show";return;}
  let job_id;
  try{
    const res=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({export_path:$("export_path").value.trim(),group_ids,
        dry_run:$("dry_run").checked,incremental:$("incremental").checked})});
    const body=await res.json();
    if(!res.ok){$("result").textContent="起任务失败："+(body.error||res.status);$("result").className="show";return;}
    job_id=body.job_id;
  }catch(err){$("result").textContent="请求出错："+err;$("result").className="show";return;}
  $("barfill").classList.add("pulse");
  const src=new EventSource("/api/jobs/"+job_id+"/stream");
  src.onmessage=(e)=>{
    const d=JSON.parse(e.data);
    if(d.stage!==undefined&&d.total!==undefined){
      const pct=d.total?Math.round(d.current/d.total*100):100;
      $("barfill").style.width=pct+"%";
      $("log").textContent+=`[${d.stage}] ${d.message}\n`;
      $("log").scrollTop=$("log").scrollHeight;
    }
    if(d.status){
      src.close();$("barfill").classList.remove("pulse");
      if(d.status==="error"){$("result").textContent="出错："+d.error;}
      else{const r=d.result||{};$("result").textContent=`完成：${r.companies||0} 公司 / ${r.people||0} 人 / ${r.links||0} 链接`;}
      $("result").className="show";
    }
  };
};
</script>
</body>
</html>
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全绿（含新 smoke）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/static/index.html tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: 操作台 UI 重做(Catppuccin双主题+动画+预估+增量)"
```

---

## Task 3: onboarding 引导向导页（Catppuccin，含装 wechat-decrypt 包）

**Files:** Modify `landing/index.html`; Test `tests/test_landing.py`

- [ ] **Step 1: 写测试 `tests/test_landing.py`**

```python
from pathlib import Path

HTML = Path("landing/index.html").read_text(encoding="utf-8")


def test_landing_has_all_steps_and_theme():
    assert "wechat-decrypt" in HTML            # 含装解密包步骤
    assert "qun-alpha serve" in HTML
    assert "import-export" in HTML
    assert "--accent" in HTML                  # Catppuccin token
    assert HTML.count('class="step"') >= 6     # 至少 6 步
    assert "themeToggle" in HTML               # 主题切换
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_landing.py -q` → Expected: FAIL（旧 landing 无这些）

- [ ] **Step 3: 用下面内容整体替换 `landing/index.html`**

```html
<!doctype html>
<html lang="zh" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊投资机会分析 · 安装引导</title>
<style>
  html[data-theme="light"]{--base:#eff1f5;--mantle:#e6e9ef;--text:#4c4f69;--subtext:#6c6f85;
    --surface0:#ccd0da;--accent:#8839ef;--yellow:#df8e1d;--shadow:0 4px 12px rgba(76,79,105,.10)}
  html[data-theme="dark"]{--base:#1e1e2e;--mantle:#181825;--text:#cdd6f4;--subtext:#a6adc8;
    --surface0:#313244;--accent:#cba6f7;--yellow:#f9e2af;--shadow:0 4px 16px rgba(0,0,0,.35)}
  *{box-sizing:border-box}
  body{font-family:'Maple Mono NF CN','JetBrains Mono','SF Mono',Consolas,monospace;
    background:var(--mantle);color:var(--text);max-width:720px;margin:0 auto;padding:40px 20px;
    line-height:1.7;transition:background .3s,color .3s}
  h1{font-size:24px;display:flex;justify-content:space-between;align-items:center}
  #themeToggle{background:transparent;border:none;color:var(--text);font-size:20px;cursor:pointer}
  .note{background:color-mix(in srgb,var(--yellow) 18%,transparent);border-left:3px solid var(--yellow);
    padding:10px 14px;border-radius:6px;margin:16px 0;font-size:14px}
  .step{background:var(--base);border-radius:12px;padding:16px 18px;margin:14px 0;box-shadow:var(--shadow)}
  .step h2{font-size:16px;margin:0 0 8px;display:flex;align-items:center;gap:10px}
  .num{display:inline-flex;width:26px;height:26px;border-radius:50%;background:var(--accent);
    color:var(--base);align-items:center;justify-content:center;font-size:13px;flex:0 0 auto}
  pre{background:var(--mantle);border-radius:8px;padding:12px 14px;overflow-x:auto;position:relative;
    font-family:inherit;font-size:13px;margin:8px 0}
  .copy{position:absolute;top:8px;right:8px;background:var(--surface0);color:var(--text);border:none;
    border-radius:6px;padding:3px 9px;font-size:12px;cursor:pointer;font-family:inherit}
  .copy:active{transform:translateY(1px)}
  .muted{color:var(--subtext);font-size:13px}
</style>
</head>
<body>
<h1>群聊投资机会分析 <button id="themeToggle" title="切换主题">◐</button></h1>
<p>从你自己的微信高质量群聊里，用<strong>本地模型</strong>提炼潜在投资机会，整理成 Notion 情报 CRM。<strong>聊天数据全程留在你本机</strong>，不上云。</p>
<div class="note">这是<strong>本地工具</strong>。下面每条命令都在你自己的 Mac 上执行，本页只是说明书。含 <code>sudo</code> 的命令请你亲自确认。</div>

<div class="step"><h2><span class="num">0</span>前置环境</h2>
<p class="muted">Python 3.10+ 与 Xcode 命令行工具。</p>
<pre><button class="copy">复制</button>xcode-select --install</pre></div>

<div class="step"><h2><span class="num">1</span>装微信解密包 wechat-decrypt</h2>
<p class="muted">克隆解密工具并装它的依赖。</p>
<pre><button class="copy">复制</button>git clone https://github.com/ylytdeng/wechat-decrypt ~/wechat-research/ylytdeng-wechat-decrypt
cd ~/wechat-research/ylytdeng-wechat-decrypt
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt</pre></div>

<div class="step"><h2><span class="num">2</span>装 qun-alpha</h2>
<pre><button class="copy">复制</button>git clone &lt;qun-alpha 仓库&gt; ~/qun-alpha
cd ~/qun-alpha
python3 -m venv .venv && source .venv/bin/activate
pip install -e .</pre></div>

<div class="step"><h2><span class="num">3</span>解密并导出微信聊天</h2>
<p class="muted">含 <code>sudo</code> 与重签名，需你亲自确认。也可跑 <code>qun-alpha decrypt-guide</code> 打印这串。</p>
<pre><button class="copy">复制</button>killall WeChat
sudo codesign --force --deep --sign - /Applications/WeChat.app
cd ~/wechat-research/ylytdeng-wechat-decrypt
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation
sudo ./find_all_keys_macos
python3 decrypt_db.py
python3 export_all_chats.py ~/qun-alpha/exported_chats/raw</pre></div>

<div class="step"><h2><span class="num">4</span>转成 qun-alpha 格式</h2>
<pre><button class="copy">复制</button>cd ~/qun-alpha
qun-alpha import-export --src-dir exported_chats/raw --out-path exported_chats/all.json --groups-only</pre></div>

<div class="step"><h2><span class="num">5</span>配置 Notion（可选）</h2>
<pre><button class="copy">复制</button>cp config.example.json config.json   # 填 notion_token
qun-alpha init-notion                 # 建三张表并打印 id，回填 config.json</pre></div>

<div class="step"><h2><span class="num">6</span>起本地操作台</h2>
<pre><button class="copy">复制</button>qun-alpha serve   # 浏览器开 http://127.0.0.1:7800</pre>
<p class="muted">选群 → 预估 → 开始 → 看进度 → 结果写进 Notion。</p></div>

<div class="note">免责：仅用于分析<strong>你自己的</strong>微信数据，请遵守相关法律法规。</div>

<script>
const savedTheme=localStorage.getItem("qa-theme")||"light";
document.documentElement.setAttribute("data-theme",savedTheme);
document.getElementById("themeToggle").onclick=()=>{
  const t=document.documentElement.getAttribute("data-theme")==="light"?"dark":"light";
  document.documentElement.setAttribute("data-theme",t);localStorage.setItem("qa-theme",t);
};
document.querySelectorAll(".copy").forEach(btn=>{
  btn.onclick=()=>{
    const pre=btn.parentElement.cloneNode(true);
    pre.querySelector(".copy").remove();
    navigator.clipboard.writeText(pre.textContent.trim());
    const old=btn.textContent;btn.textContent="已复制";setTimeout(()=>btn.textContent=old,1200);
  };
});
</script>
</body>
</html>
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_landing.py -q` → Expected: 1 passed
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add landing/index.html tests/test_landing.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: onboarding 向导页重做(Catppuccin双主题+复制按钮+装wechat-decrypt步骤)"
```

---

## 完成标准（Spec B）
- [ ] `pytest -q` 全绿
- [ ] web 有 /api/estimate、/api/jobs、/api/jobs/{id}/resume；POST /api/jobs 透传 incremental
- [ ] 操作台 UI：Catppuccin 双主题（记忆）、预估面板、增量开关、进度脉冲动画、结果淡入
- [ ] onboarding 向导：双主题、复制按钮、6+ 步（含装 wechat-decrypt 包）
- [ ] 既有测试不回归

## 手动验收（用户视觉）
`qun-alpha serve` → 切主题、加载群、预估、增量开关、开始看动画；浏览器打开 landing/index.html 看向导。

## 后续（不在本计划）
模式 Y（线上驱动本地 agent）、resume/jobs 列表在前端可视化、Windows/Linux 向导分支。
