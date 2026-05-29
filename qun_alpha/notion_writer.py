from __future__ import annotations
from typing import Any, Callable
from qun_alpha.models import Company


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
    """按标题等值查存量页，命中返回 page_id，否则 None。"""
    resp = client.databases.query(
        database_id=database_id,
        filter={"property": title_prop, "title": {"equals": title_value}},
    )
    results = resp.get("results", [])
    return results[0]["id"] if results else None


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
