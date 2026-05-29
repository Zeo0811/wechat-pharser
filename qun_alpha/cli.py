from __future__ import annotations
from typing import Any, Callable, Optional
import typer
from qun_alpha import chat_reader, extractor, aggregator, notion_writer
from qun_alpha.config import load_config

app = typer.Typer(help="群聊投资机会分析")


def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 notion_client: Any, companies_db_id: str,
                 dry_run: bool) -> dict:
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)

    raw: list = []
    for ch in chunks:
        raw.extend(extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir))

    companies, people, links = aggregator.aggregate(raw)
    payloads = notion_writer.write_companies(
        companies, client=notion_client, database_id=companies_db_id, dry_run=dry_run)

    return {
        "chunks": len(chunks),
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "notion_payloads": payloads,
    }


@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒"),
    config_path: str = typer.Option("config.json"),
    dry_run: bool = typer.Option(True, help="只预演不写 Notion"),
):
    """分析指定群的指定时间段，输出实体并（可选）写 Notion。"""
    cfg = load_config(config_path)
    client = None
    if not dry_run:
        from notion_client import Client
        client = Client(auth=cfg.notion_token)

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
        dry_run=dry_run,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")


if __name__ == "__main__":
    app()
