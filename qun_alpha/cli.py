from __future__ import annotations
from typing import Any, Callable, Optional
import typer
from qun_alpha import chat_reader, extractor, aggregator, notion_writer, orchestrator
from qun_alpha.config import load_config

app = typer.Typer(help="群聊投资机会分析")


def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 notion_client: Any,
                 companies_db_id: str, people_db_id: str, links_db_id: str,
                 dry_run: bool) -> dict:
    return orchestrator.run_job(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=max_messages, prompt_version=prompt_version,
        runner=runner, cache_dir=cache_dir, notion_client=notion_client,
        companies_db_id=companies_db_id, people_db_id=people_db_id,
        links_db_id=links_db_id, dry_run=dry_run,
    )


def _notion_client(cfg):
    from notion_client import Client
    return Client(auth=cfg.notion_token)


@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒（默认≈2033，等于无上界）"),
    config_path: str = typer.Option("config.json"),
    dry_run: bool = typer.Option(True, help="只预演不写 Notion"),
):
    """分析指定群的指定时间段，输出实体并（可选）写 Notion 三张表。"""
    cfg = load_config(config_path)
    client = None if dry_run else _notion_client(cfg)
    result = run_pipeline(
        export_path=export_path,
        group_ids=[g.strip() for g in groups.split(",") if g.strip()],
        start=start, end=end,
        max_messages=cfg.max_messages_per_chunk,
        prompt_version=cfg.prompt_version,
        runner=extractor.default_claude_runner,
        cache_dir=cfg.cache_dir,
        notion_client=client,
        companies_db_id=cfg.notion_companies_db_id,
        people_db_id=cfg.notion_people_db_id,
        links_db_id=cfg.notion_links_db_id,
        dry_run=dry_run,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")


@app.command("init-notion")
def init_notion(config_path: str = typer.Option("config.json")):
    """在配置的父页面下创建 Companies/People/Links 三张数据库，并打印 database_id。"""
    cfg = load_config(config_path)
    client = _notion_client(cfg)
    ids = notion_writer.ensure_databases(client, parent_page_id=cfg.notion_parent_page_id)
    typer.echo("已创建数据库，请把下面的 id 填进 config.json：")
    for key, db_id in ids.items():
        typer.echo(f"  {key}: {db_id}")


if __name__ == "__main__":
    app()
