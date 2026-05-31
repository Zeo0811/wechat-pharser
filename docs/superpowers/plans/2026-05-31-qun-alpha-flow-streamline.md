# 流程精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 网页自动加载群（去掉路径输入+加载按钮）、解密卡片优先、首次无数据引导解密；CLI 装完引导直接启动。

**Architecture:** 新增 `GET /api/config`（export_path + has_export）；前端首屏据此自动拉群或显示解密优先态；install.sh 末尾引导 + [Y/n] 自动 serve。

**Tech Stack:** FastAPI、原生 JS、bash、pytest。`.venv` + `.venv/bin/pytest`。

---

## Task 1: web /api/config 端点

**Files:** Modify `qun_alpha/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: 追加失败测试到 `tests/test_web.py` 末尾**

```python
def test_config_endpoint(tmp_path):
    f = tmp_path / "all.json"
    f.write_text("[]", encoding="utf-8")

    class Cfg:
        export_path = str(f)
        model_backend = "codex"

    app = create_app(manager=JobManager(),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [],
                     config_loader=lambda: Cfg())
    d = TestClient(app).get("/api/config").json()
    assert d["export_path"] == str(f)
    assert d["has_export"] is True
    assert d["model_backend"] == "codex"


def test_config_endpoint_no_export(tmp_path):
    class Cfg:
        export_path = str(tmp_path / "nope.json")
        model_backend = "claude"

    app = create_app(manager=JobManager(),
                     target_factory=lambda p: (lambda e: {}),
                     groups_provider=lambda e: [],
                     config_loader=lambda: Cfg())
    assert TestClient(app).get("/api/config").json()["has_export"] is False
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_config_endpoint -q` → Expected: FAIL (404)

- [ ] **Step 3: 修改 `qun_alpha/web.py`** — 在 `create_app` 内、`return app` 之前加端点：
```python
    @app.get("/api/config")
    def config_ep():
        import os
        try:
            cfg = config_loader()
            export_path = cfg.export_path
            backend = cfg.model_backend
        except Exception:
            export_path, backend = "exported_chats/all.json", "claude"
        return {"export_path": export_path,
                "has_export": os.path.exists(export_path),
                "model_backend": backend}
```

- [ ] **Step 4: 运行确认通过 + 全套**
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/web.py tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: web /api/config 端点(export_path/has_export/backend)"
```

---

## Task 2: 操作台 UI 流程重排（自动加载群 + 解密优先）

**Files:** Modify `qun_alpha/static/index.html`; Test `tests/test_web.py`

- [ ] **Step 1: 追加 smoke 测试到 `tests/test_web.py` 末尾**

```python
def test_index_streamlined_flow():
    client = _client(JobManager())
    html = client.get("/").text
    assert "/api/config" in html                 # 首屏拉配置
    assert 'id="export_path"' not in html         # 移除路径输入
    assert 'id="loadGroups"' not in html          # 移除加载按钮
    assert "解密导出后" in html                    # 群占位文案
    # 解密卡片在群卡片之前
    assert html.index("decryptBtn") < html.index('id="groups"')
    assert 'id="groupSearch"' in html and 'id="start"' in html
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_web.py::test_index_streamlined_flow -q` → Expected: FAIL

- [ ] **Step 3: 用下面内容整体替换 `qun_alpha/static/index.html`**

```html
<!doctype html>
<html lang="zh" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊投资机会分析</title>
<style>
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
  .card.highlight{outline:2px solid var(--accent);outline-offset:1px}
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
  #groups .grpitem{display:flex}
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

<div class="card" id="decryptCard">
  <label>解密微信（首次设置签名后，日常只点②）</label>
  <div class="row" style="margin-top:10px">
    <button id="codesignBtn" class="ghost">① 重签名（首次）</button>
    <button id="decryptBtn">② 解密并导出</button>
  </div>
  <div class="muted" style="margin-top:8px">①会退出微信并弹管理员密码框；之后请重开并登录微信，再点②。②需微信开着且已登录。</div>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <label>选择群</label>
    <button id="selectAll" class="ghost" style="padding:4px 10px;font-size:12px">全选/全不选</button>
  </div>
  <input type="text" id="groupSearch" placeholder="搜索群名…" style="margin:8px 0">
  <div id="groups"><div class="muted" id="groupsPlaceholder">解密导出后，群列表会自动出现在这里。首次请先点上方「② 解密并导出」。</div></div>
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
let CFG={export_path:"exported_chats/all.json", has_export:false};

const savedTheme=localStorage.getItem("qa-theme")||"light";
document.documentElement.setAttribute("data-theme",savedTheme);
$("themeToggle").onclick=()=>{
  const t=document.documentElement.getAttribute("data-theme")==="light"?"dark":"light";
  document.documentElement.setAttribute("data-theme",t);
  localStorage.setItem("qa-theme",t);
};

const selectedGroups=()=>[...document.querySelectorAll(".grp:checked")].map(e=>e.value);

async function loadGroups(){
  try{
    const res=await fetch("/api/groups?export_path="+encodeURIComponent(CFG.export_path));
    if(!res.ok){$("groups").innerHTML=`<div class="muted">加载群失败：${res.status}</div>`;return;}
    const groups=await res.json();
    if(!groups.length){$("groups").innerHTML=`<div class="muted">导出里没有群。先点「② 解密并导出」。</div>`;return;}
    $("groups").innerHTML=groups.map(g=>{
      const badge = g.processed ? ` <span class="muted" style="color:var(--green)">✓已分析·${g.runs||1}次</span>` : "";
      return `<label class="grpitem"><input type="checkbox" class="grp" value="${g.group_id}"> ${g.group_name} <span class="muted">(${g.count})</span>${badge}</label>`;
    }).join("");
  }catch(err){$("groups").innerHTML=`<div class="muted">请求出错：${err}</div>`;}
}

// 首屏：拉配置，有导出就自动加载群，没有就引导去解密
fetch("/api/config").then(r=>r.json()).then(c=>{
  CFG=c;
  if(c.has_export){ loadGroups(); }
  else{ $("decryptCard").classList.add("highlight"); }
}).catch(()=>{});

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
  if(b)streamJob(b.job_id,()=>{
    if(b.export_path)CFG.export_path=b.export_path;
    $("decryptCard").classList.remove("highlight");
    $("result").textContent="解密导出完成，正在加载群…";
    loadGroups();
  });
};

$("groupSearch").oninput=()=>{
  const q=$("groupSearch").value.trim().toLowerCase();
  document.querySelectorAll("#groups .grpitem").forEach(el=>{
    el.style.display = el.textContent.toLowerCase().includes(q) ? "flex" : "none";
  });
};
$("selectAll").onclick=()=>{
  const vis=[...document.querySelectorAll("#groups .grpitem")].filter(el=>el.style.display!=="none");
  const boxes=vis.map(el=>el.querySelector(".grp"));
  const allOn=boxes.every(b=>b.checked);
  boxes.forEach(b=>b.checked=!allOn);
};

$("estimateBtn").onclick=async()=>{
  const gids=selectedGroups();
  if(!gids.length){$("estimate").textContent="请先勾选群再预估。";return;}
  $("estimate").textContent="预估中…";
  try{
    const q=new URLSearchParams({export_path:CFG.export_path,groups:gids.join(",")});
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
  if(!group_ids.length){$("result").textContent="请先选至少一个群（没群就先点②解密并导出）。";$("result").className="show";return;}
  let job_id;
  try{
    const res=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({export_path:CFG.export_path,group_ids,
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
Run: `.venv/bin/pytest tests/test_web.py -q` → Expected: 全过（旧 smoke 仍过：groups/start/themeToggle/groupSearch/已分析 都在）
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add qun_alpha/static/index.html tests/test_web.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: 操作台流程精简(自动加载群+解密优先, 去路径输入)"
```

---

## Task 3: install.sh 装完引导 + 可选自动启动

**Files:** Modify `install/install.sh`; Test `tests/test_install_sh.py`

- [ ] **Step 1: 追加测试到 `tests/test_install_sh.py` 末尾**

```python
def test_install_sh_guides_start():
    t = SH.read_text(encoding="utf-8")
    assert "现在启动" in t          # 询问是否启动
    assert "/dev/tty" in t          # 从 tty 读
    assert "qun-alpha serve" in t
```

- [ ] **Step 2: 运行确认失败**
Run: `.venv/bin/pytest tests/test_install_sh.py::test_install_sh_guides_start -q` → Expected: FAIL

- [ ] **Step 3: 修改 `install/install.sh` 第 10 步（体检 + 下一步）**

找到文件末尾的：
```bash
# 10. 体检 + 下一步
c "依赖体检"
"$QUN_ALPHA_HOME/.venv/bin/qun-alpha" doctor || true
echo
c "完成！下一步："
echo "  qun-alpha decrypt-guide   # 看解密说明"
echo "  qun-alpha serve           # 起本地操作台 http://127.0.0.1:7800"
```
替换为：
```bash
# 10. 体检 + 引导启动
c "依赖体检"
"$QUN_ALPHA_HOME/.venv/bin/qun-alpha" doctor || true
echo
c "装好了！打开操作台后，点「② 解密并导出」即可开始（首次先点①重签名）。"
printf "现在启动操作台吗？[Y/n]: "
read -r ans </dev/tty || ans="n"
case "${ans:-Y}" in
  [nN]*) echo "稍后手动启动：qun-alpha serve" ;;
  *) exec "$QUN_ALPHA_HOME/.venv/bin/qun-alpha" serve ;;
esac
```

- [ ] **Step 4: 语法 + 测试**
Run: `bash -n install/install.sh` → Expected: exit 0
Run: `.venv/bin/pytest tests/test_install_sh.py -q` → Expected: 全过
Run: `.venv/bin/pytest -q` → Expected: 全绿

- [ ] **Step 5: Commit**
```bash
git add install/install.sh tests/test_install_sh.py
git -c user.name="zeoooo" -c user.email="zeo0811@gmail.com" commit -m "feat: install.sh 装完引导 + [Y/n] 自动启动操作台"
```

---

## 完成标准
- [ ] `pytest -q` 全绿
- [ ] `/api/config` 返回 export_path/has_export/backend
- [ ] 网页首屏自动拉群（有导出）/ 引导解密（无导出），无路径输入框与加载按钮，解密卡片在前
- [ ] install.sh 末尾引导 + [Y/n] 自动 serve
- [ ] 既有测试不回归
```
