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
