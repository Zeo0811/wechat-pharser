from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Optional
from qun_alpha import chat_reader, extractor, aggregator, notion_writer


@dataclass
class ProgressEvent:
    stage: str          # read | extract | aggregate | write | done
    current: int
    total: int
    message: str


Emit = Callable[["ProgressEvent"], None]


def _noop(_ev: "ProgressEvent") -> None:
    pass


def run_job(*, export_path: str, group_ids: list[str], start: int, end: int,
            max_messages: int, prompt_version: str,
            runner: Callable[[str], str], cache_dir: Optional[str],
            notion_client: Any,
            companies_db_id: str, people_db_id: str, links_db_id: str,
            dry_run: bool, emit: Emit = _noop) -> dict:
    emit(ProgressEvent("read", 0, 1, "读取并切块"))
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)
    total = len(chunks)
    emit(ProgressEvent("read", 1, 1, f"共 {total} 块"))

    raw: list = []
    for i, ch in enumerate(chunks):
        raw.extend(extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir))
        emit(ProgressEvent("extract", i + 1, total, f"抽取 {i + 1}/{total} 块"))

    emit(ProgressEvent("aggregate", 0, 1, "聚合打分"))
    companies, people, links = aggregator.aggregate(raw)
    emit(ProgressEvent("aggregate", 1, 1,
                       f"{len(companies)}公司/{len(people)}人/{len(links)}链接"))

    emit(ProgressEvent("write", 0, 1, "写 Notion"))
    company_payloads = notion_writer.write_companies(
        companies, client=notion_client, database_id=companies_db_id, dry_run=dry_run)
    people_payloads = notion_writer.write_people(
        people, client=notion_client, database_id=people_db_id, dry_run=dry_run)
    link_payloads = notion_writer.write_links(
        links, client=notion_client, database_id=links_db_id, dry_run=dry_run)
    emit(ProgressEvent("write", 1, 1, "写入完成"))

    result = {
        "chunks": total,
        "raw_entities": len(raw),
        "companies": len(companies),
        "people": len(people),
        "links": len(links),
        "company_payloads": company_payloads,
        "people_payloads": people_payloads,
        "link_payloads": link_payloads,
    }
    emit(ProgressEvent("done", 1, 1, "完成"))
    return result
