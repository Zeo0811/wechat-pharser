from fastapi.testclient import TestClient
from qun_alpha.jobs import JobManager
from qun_alpha.web import create_app


def _client(manager):
    def groups_provider(export_path):
        return [{"group_id": "g1", "group_name": "AI投资群", "count": 4}]

    def target_factory(params):
        def target(emit):
            emit({"stage": "read", "current": 1, "total": 1, "message": "ok"})
            emit({"stage": "done", "current": 1, "total": 1, "message": "完成"})
            return {"companies": 1, "people": 0, "links": 0,
                    "group_ids": params["group_ids"]}
        return target

    app = create_app(manager=manager, target_factory=target_factory,
                     groups_provider=groups_provider)
    return TestClient(app)


def test_groups_endpoint():
    client = _client(JobManager())
    r = client.get("/api/groups", params={"export_path": "x.json"})
    assert r.status_code == 200
    assert r.json()[0]["group_id"] == "g1"


def test_start_job_and_poll_status():
    mgr = JobManager()
    client = _client(mgr)
    r = client.post("/api/jobs", json={"export_path": "x.json",
                                       "group_ids": ["g1"], "dry_run": True})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    mgr.join(job_id)
    s = client.get(f"/api/jobs/{job_id}")
    assert s.status_code == 200
    body = s.json()
    assert body["status"] == "done"
    assert body["result"]["companies"] == 1
    assert body["result"]["group_ids"] == ["g1"]
    assert len(body["events"]) == 2


def test_unknown_job_404():
    client = _client(JobManager())
    assert client.get("/api/jobs/nope").status_code == 404


def test_start_job_target_build_failure_returns_400():
    def boom_factory(params):
        raise FileNotFoundError("配置文件不存在：config.json")
    app = create_app(manager=JobManager(), target_factory=boom_factory,
                     groups_provider=lambda ep: [])
    client = TestClient(app)
    r = client.post("/api/jobs", json={"export_path": "x", "group_ids": ["g1"]})
    assert r.status_code == 400
    assert "config.json" in r.json()["error"]


from qun_alpha.web import iter_sse


def test_iter_sse_replays_events_then_terminal():
    mgr = JobManager()

    def target(emit):
        emit({"stage": "read", "current": 1, "total": 1, "message": "ok"})
        emit({"stage": "extract", "current": 1, "total": 1, "message": "块"})
        return {"companies": 2}

    job_id = mgr.start(target)
    mgr.join(job_id)
    chunks = list(iter_sse(mgr, job_id, poll=0.0))
    text = "".join(chunks)
    assert text.count("data:") >= 3          # 2 个进度 + 1 个终态
    assert '"stage": "read"' in text or '"stage":"read"' in text
    assert '"status": "done"' in text or '"status":"done"' in text


def test_iter_sse_unknown_job():
    chunks = list(iter_sse(JobManager(), "nope", poll=0.0))
    assert any("error" in c for c in chunks)


def test_stream_endpoint_content_type():
    mgr = JobManager()
    client = _client(mgr)
    r = client.post("/api/jobs", json={"export_path": "x.json",
                                       "group_ids": ["g1"], "dry_run": True})
    job_id = r.json()["job_id"]
    mgr.join(job_id)
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert "data:" in body


def test_index_served():
    client = _client(JobManager())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'id="groups"' in r.text
    assert "群聊投资机会" in r.text


def test_build_app_returns_fastapi():
    from qun_alpha.cli import build_app
    from fastapi import FastAPI
    app = build_app()
    assert isinstance(app, FastAPI)


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


def test_index_has_redesign_elements():
    client = _client(JobManager())
    html = client.get("/").text
    assert 'id="themeToggle"' in html
    assert 'id="estimate"' in html
    assert 'id="incremental"' in html
    assert "--accent" in html
    assert 'id="groups"' in html and 'id="start"' in html


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


def test_index_has_decrypt_card():
    client = _client(JobManager())
    html = client.get("/").text
    assert 'id="codesignBtn"' in html
    assert 'id="decryptBtn"' in html
    assert "解密微信" in html
