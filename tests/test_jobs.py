import time
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
