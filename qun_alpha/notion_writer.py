from __future__ import annotations
from typing import Any
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


def write_companies(companies: list[Company], client: Any, database_id: str,
                    dry_run: bool = False) -> list[Any]:
    results = []
    for c in companies:
        payload = {
            "parent": {"database_id": database_id},
            "properties": company_to_properties(c),
        }
        if dry_run:
            results.append(payload)
            continue
        page = client.pages.create(**payload)
        results.append(page["id"])
    return results
