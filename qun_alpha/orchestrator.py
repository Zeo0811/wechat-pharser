from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
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
            dry_run: bool, emit: Emit = _noop,
            concurrency: int = 3, job_store: Any = None,
            job_id: Optional[str] = None,
            incremental: bool = False, cursor_store: Any = None) -> dict:
    emit(ProgressEvent("read", 0, 1, "读取并切块"))
    messages = chat_reader.load_export(export_path)
    filtered = chat_reader.filter_messages(
        messages, group_ids=group_ids, start=start, end=end, drop_noise=True)
    if incremental and cursor_store is not None:
        filtered = [m for m in filtered
                    if m.timestamp > cursor_store.get(m.group_id)]
    chunks = chat_reader.chunk_messages(
        filtered, max_messages=max_messages, prompt_version=prompt_version)
    total = len(chunks)
    emit(ProgressEvent("read", 1, 1, f"共 {total} 块"))

    raw: list = []
    done = 0

    def _extract(ch):
        return ch, extractor.extract_chunk(ch, runner=runner, cache_dir=cache_dir)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_extract, ch) for ch in chunks]
        for fut in as_completed(futures):
            done += 1
            try:
                ch, entities = fut.result()
                raw.extend(entities)
                if job_store is not None and job_id is not None:
                    job_store.mark_done(job_id, ch.chunk_id)
            except Exception:
                if job_store is not None and job_id is not None:
                    job_store.mark_failed(job_id, f"unknown_{done}")
            emit(ProgressEvent("extract", done, total, f"抽取 {done}/{total} 块"))

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
    if incremental and cursor_store is not None:
        latest: dict[str, int] = {}
        for ch in chunks:
            latest[ch.group_id] = max(latest.get(ch.group_id, 0), ch.time_end)
        for gid, ts in latest.items():
            cursor_store.set(gid, ts)
    emit(ProgressEvent("done", 1, 1, "完成"))
    return result
