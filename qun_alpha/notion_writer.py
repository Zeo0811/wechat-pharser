from __future__ import annotations
import logging
from typing import Any, Callable
from qun_alpha.models import Company, Person, Link

logger = logging.getLogger(__name__)


def _rt(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text[:2000]}}]}


def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def company_to_properties(c: Company) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Company": _title(c.name),
        "Score": {"number": c.score},
        "Mntns": {"number": c.mentions},
        "Status": {"select": {"name": c.status}},
        "Signal": _rt(c.signal),
        "Confidence": {"number": c.confidence},
    }
    if c.sector:
        props["Sector"] = {"select": {"name": c.sector}}
    if c.stage:
        props["Stage"] = {"select": {"name": c.stage}}
    if c.financials:
        props["Financials"] = _rt(c.financials)
    if c.investors:
        props["Investors"] = {"multi_select": [{"name": i[:100]} for i in c.investors]}
    if c.suggested_action:
        props["Action"] = {"select": {"name": c.suggested_action}}
    return props


def _find_page_id(client: Any, database_id: str, title_prop: str,
                  title_value: str):
    """按标题等值查存量页，命中返回 page_id，否则 None。
    查询值截断到 2000 与写入时 _title 的截断保持一致，避免超长名每次重建。"""
    resp = client.databases.query(
        database_id=database_id,
        filter={"property": title_prop, "title": {"equals": title_value[:2000]}},
    )
    results = resp.get("results", [])
    if not results:
        return None
    if len(results) > 1:
        logger.warning("库 %s 中标题 %r 命中 %d 个页面，更新第一个，其余将变陈旧",
                       database_id, title_value, len(results))
    return results[0]["id"]


def _upsert_all(items: list, client: Any, database_id: str, title_prop: str,
                name_of: Callable[[Any], str],
                to_props: Callable[[Any], dict], dry_run: bool) -> list:
    """dry_run 只返回 payload；实跑先查后 update/create。"""
    results: list = []
    for it in items:
        props = to_props(it)
        if dry_run:
            results.append({"parent": {"database_id": database_id},
                            "properties": props})
            continue
        existing = _find_page_id(client, database_id, title_prop, name_of(it))
        if existing:
            client.pages.update(page_id=existing, properties=props)
            results.append(existing)
        else:
            page = client.pages.create(
                parent={"database_id": database_id}, properties=props)
            results.append(page["id"])
    return results


def write_companies(companies: list[Company], client: Any, database_id: str,
                    dry_run: bool = False) -> list[Any]:
    return _upsert_all(companies, client, database_id, "Company",
                       lambda c: c.name, company_to_properties, dry_run)


def person_to_properties(p: Person) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Person": _title(p.name),
        "Mntns": {"number": p.mentions},
    }
    if p.role:
        props["Role"] = _rt(p.role)
    if p.affiliated_companies:
        props["Affiliated"] = {
            "multi_select": [{"name": c[:100]} for c in p.affiliated_companies]}
    if p.notable_quotes:
        props["Quotes"] = _rt(" | ".join(p.notable_quotes))
    return props


def write_people(people: list[Person], client: Any, database_id: str,
                 dry_run: bool = False) -> list[Any]:
    return _upsert_all(people, client, database_id, "Person",
                       lambda p: p.name, person_to_properties, dry_run)


def link_to_properties(link: Link) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Link": _title(link.url),
    }
    if link.title:
        props["Title"] = _rt(link.title)
    if link.shared_by:
        props["SharedBy"] = {
            "multi_select": [{"name": s[:100]} for s in link.shared_by]}
    if link.related_companies:
        props["Related"] = {
            "multi_select": [{"name": c[:100]} for c in link.related_companies]}
    return props


def write_links(links: list[Link], client: Any, database_id: str,
                dry_run: bool = False) -> list[Any]:
    return _upsert_all(links, client, database_id, "Link",
                       lambda link: link.url, link_to_properties, dry_run)


_STATUS_OPTIONS = [{"name": "emerging"}, {"name": "known"},
                   {"name": "noise"}, {"name": "unclear"}]

_COMPANIES_SCHEMA = {
    "Company": {"title": {}},
    "Score": {"number": {}},
    "Mntns": {"number": {}},
    "Status": {"select": {"options": _STATUS_OPTIONS}},
    "Signal": {"rich_text": {}},
    "Confidence": {"number": {}},
    "Sector": {"select": {}},
    "Stage": {"select": {}},
    "Financials": {"rich_text": {}},
    "Investors": {"multi_select": {}},
    "Action": {"select": {}},
}

_PEOPLE_SCHEMA = {
    "Person": {"title": {}},
    "Mntns": {"number": {}},
    "Role": {"rich_text": {}},
    "Affiliated": {"multi_select": {}},
    "Quotes": {"rich_text": {}},
}

_LINKS_SCHEMA = {
    "Link": {"title": {}},
    "Title": {"rich_text": {}},
    "SharedBy": {"multi_select": {}},
    "Related": {"multi_select": {}},
}

_DB_SPECS = [
    ("companies", "Companies", _COMPANIES_SCHEMA),
    ("people", "People", _PEOPLE_SCHEMA),
    ("links", "Links", _LINKS_SCHEMA),
]


def ensure_databases(client: Any, parent_page_id: str, dry_run: bool = False):
    """在父页面下创建 Companies/People/Links 三库。
    dry_run 返回 create payload 列表；实跑返回 {key: database_id}。"""
    if dry_run:
        return [
            {"parent": {"page_id": parent_page_id},
             "title": [{"text": {"content": db_title}}],
             "properties": schema}
            for _, db_title, schema in _DB_SPECS
        ]
    ids: dict[str, str] = {}
    for key, db_title, schema in _DB_SPECS:
        db = client.databases.create(
            parent={"page_id": parent_page_id},
            title=[{"text": {"content": db_title}}],
            properties=schema,
        )
        ids[key] = db["id"]
    return ids
