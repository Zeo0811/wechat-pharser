from __future__ import annotations
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from qun_alpha import chat_reader, orchestrator, extractor, estimate as estimate_mod, decrypt_service, runners
from qun_alpha.cursor_store import CursorStore
from qun_alpha.job_store import JobStore
from qun_alpha.jobs import JobManager
from qun_alpha.processed_store import ProcessedStore

TargetFactory = Callable[[dict], Callable[[Callable[[Any], None]], dict]]
GroupsProvider = Callable[[str], list]


def _ev(e: Any) -> dict:
    """ProgressEvent(dataclass) → dict；已是 dict 则原样返回。"""
    if dataclasses.is_dataclass(e) and not isinstance(e, type):
        return dataclasses.asdict(e)
    return e


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def iter_sse(manager: JobManager, job_id: str, poll: float = 0.05):
    """逐个吐进度事件，job 终态时吐一条终态事件后结束。"""
    sent = 0
    while True:
        job = manager.get(job_id)
        if job is None:
            yield _sse({"stage": "error", "message": "unknown job"})
            return
        while sent < len(job.events):
            yield _sse(_ev(job.events[sent]))
            sent += 1
        if job.status in ("done", "error"):
            yield _sse({"status": job.status, "result": job.result,
                        "error": job.error})
            return
        time.sleep(poll)


def _default_target_factory(params: dict):
    import os
    from qun_alpha.config import load_config
    cfg = load_config(params.get("config_path", "config.json"))
    incremental = params.get("incremental", False)
    concurrency = int(params.get("concurrency", 3))
    cursor = CursorStore()
    backend = params.get("model") or cfg.model_backend
    # 抽取要调模型 CLI，先确认它在；缺失 → start_job 返回 400
    runners.ensure_available(backend)
    report_dir = params.get("report_dir") or os.path.join(
        os.path.expanduser("~"), "Downloads")

    def target(emit):
        result = orchestrator.run_job(
            export_path=params["export_path"],
            group_ids=params["group_ids"],
            start=params.get("start", 0),
            end=params.get("end", 2_000_000_000),
            max_messages=cfg.max_messages_per_chunk,
            prompt_version=cfg.prompt_version,
            runner=runners.get_runner(backend),
            cache_dir=cfg.cache_dir,
            report_dir=report_dir, emit=emit,
            concurrency=concurrency,
            incremental=incremental, cursor_store=cursor,
        )
        try:
            ProcessedStore().mark(params.get("group_ids", []))
        except Exception:
            pass
        return result
    return target


def _default_estimator(export_path: str, group_ids: list, start: int, end: int) -> dict:
    from qun_alpha.config import load_config
    cfg = load_config("config.json")
    return estimate_mod.estimate_run(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=cfg.max_messages_per_chunk, prompt_version=cfg.prompt_version,
        cache_dir=cfg.cache_dir)


def create_app(*, manager: Optional[JobManager] = None,
               target_factory: Optional[TargetFactory] = None,
               groups_provider: Optional[GroupsProvider] = None,
               job_store: Optional[Any] = None,
               estimator: Optional[Callable] = None,
               decrypt_runner: Optional[Callable] = None,
               config_loader: Optional[Callable] = None,
               processed_store: Optional[Any] = None) -> FastAPI:
    if manager is None:
        job_store = job_store or JobStore()
        manager = JobManager(job_store=job_store)
    target_factory = target_factory or _default_target_factory
    groups_provider = groups_provider or chat_reader.list_groups
    estimator = estimator or _default_estimator
    decrypt_runner = decrypt_runner or decrypt_service.default_runner
    if config_loader is None:
        from qun_alpha.config import load_config
        config_loader = lambda: load_config("config.json")
    processed_store = processed_store or ProcessedStore()
    app = FastAPI(title="群聊投资机会分析")

    @app.get("/api/groups")
    def groups(export_path: str):
        out = []
        for g in groups_provider(export_path):
            g = dict(g)
            p = processed_store.get(g["group_id"])
            g["processed"] = bool(p)
            if p:
                g["runs"] = p.get("runs")
                g["last"] = p.get("last")
            out.append(g)
        return JSONResponse(out)

    @app.post("/api/jobs")
    async def start_job(req: Request):
        params = await req.json()
        try:
            target = target_factory(params)
        except Exception as e:               # 构建任务失败（如缺 config.json）→ 给前端可读错误
            return JSONResponse({"error": str(e)}, status_code=400)
        job_id = manager.start(target)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "events": [_ev(e) for e in job.events],
        }

    @app.get("/api/jobs/{job_id}/stream")
    def stream(job_id: str):
        return StreamingResponse(iter_sse(manager, job_id),
                                 media_type="text/event-stream")

    @app.get("/")
    def index():
        html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

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

    return app
