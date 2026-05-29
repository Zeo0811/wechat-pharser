from qun_alpha.jobs import JobManager


def test_job_runs_and_collects_events_and_result():
    mgr = JobManager()

    def target(emit):
        emit("e1")
        emit("e2")
        return {"ok": True}

    job_id = mgr.start(target)
    mgr.join(job_id)
    job = mgr.get(job_id)
    assert job.status == "done"
    assert job.events == ["e1", "e2"]
    assert job.result == {"ok": True}
    assert job.error is None


def test_job_records_error():
    mgr = JobManager()

    def boom(emit):
        emit("started")
        raise ValueError("炸了")

    job_id = mgr.start(boom)
    mgr.join(job_id)
    job = mgr.get(job_id)
    assert job.status == "error"
    assert "炸了" in job.error
    assert job.events == ["started"]


def test_job_ids_unique():
    mgr = JobManager()
    a = mgr.start(lambda emit: {})
    b = mgr.start(lambda emit: {})
    assert a != b


def test_get_unknown_returns_none():
    assert JobManager().get("nope") is None


from qun_alpha.job_store import JobStore


def test_start_persists_params_and_resume(tmp_path):
    store = JobStore(dir=str(tmp_path / "jobs"))
    mgr = JobManager(job_store=store)
    runs = []

    def build_target(params):
        def target(emit):
            runs.append(params["n"])
            return {"n": params["n"]}
        return target

    job_id = mgr.start(build_target({"n": 1}), params={"n": 1})
    mgr.join(job_id)
    rec = store.load(job_id)
    assert rec["params"]["n"] == 1
    assert rec["status"] == "done"

    mgr.resume(job_id, build_target)
    mgr.join(job_id)
    assert runs == [1, 1]


def test_start_without_store_still_works():
    mgr = JobManager()
    jid = mgr.start(lambda emit: {"ok": True})
    mgr.join(jid)
    assert mgr.get(jid).status == "done"
