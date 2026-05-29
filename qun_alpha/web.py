from __future__ import annotations
import dataclasses
from typing import Any, Callable, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from qun_alpha import chat_reader
from qun_alpha.jobs import JobManager

TargetFactory = Callable[[dict], Callable[[Callable[[Any], None]], dict]]
GroupsProvider = Callable[[str], list]


def _ev(e: Any) -> dict:
    """ProgressEvent(dataclass) → dict；已是 dict 则原样返回。"""
    if dataclasses.is_dataclass(e) and not isinstance(e, type):
        return dataclasses.asdict(e)
    return e


def _default_target_factory(params: dict):
    from qun_alpha.config import load_config
    from qun_alpha import orchestrator, extractor
    cfg = load_config(params.get("config_path", "config.json"))
    dry_run = params.get("dry_run", True)
    client = None
    if not dry_run:
        from notion_client import Client
        client = Client(auth=cfg.notion_token)

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
            dry_run=dry_run,
            emit=emit,
        )
    return target


def create_app(*, manager: Optional[JobManager] = None,
               target_factory: Optional[TargetFactory] = None,
               groups_provider: Optional[GroupsProvider] = None) -> FastAPI:
    manager = manager or JobManager()
    target_factory = target_factory or _default_target_factory
    groups_provider = groups_provider or chat_reader.list_groups
    app = FastAPI(title="群聊投资机会分析")

    @app.get("/api/groups")
    def groups(export_path: str):
        return JSONResponse(groups_provider(export_path))

    @app.post("/api/jobs")
    async def start_job(req: Request):
        params = await req.json()
        job_id = manager.start(target_factory(params))
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

    return app
