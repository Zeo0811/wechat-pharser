from __future__ import annotations
import re
from qun_alpha.models import RawEntity, Company, Person, Link, Status

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    return _WS.sub("", name.strip().lower())


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def score_company(group: list[RawEntity]) -> int:
    """0-100 启发式打分。"""
    mentions = len(group)
    confidences = [e.confidence for e in group if e.confidence is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    has_fin = any(e.financials for e in group)
    investors = _dedup_keep_order([i for e in group for i in e.investors])
    commentary_len = max((len(e.commentary) for e in group), default=0)

    score = 0.0
    score += min(mentions, 5) * 8          # 提及次数，封顶 40
    score += avg_conf * 25                 # 置信度，最高 25
    score += 15 if has_fin else 0          # 有财务信号
    score += min(len(investors), 2) * 6    # 投资人动向，封顶 12
    score += min(commentary_len, 80) / 80 * 8   # 点评实质度，最高 8
    return max(0, min(100, round(score)))


def _status_from_score(score: int) -> Status:
    if score < 20:
        return "noise"
    if score < 40:
        return "unclear"
    return "emerging"


def _build_signal(group: list[RawEntity]) -> str:
    parts = []
    for e in group:
        seg = e.quote.strip()
        if e.commentary.strip():
            seg = f"{seg} — {e.commentary.strip()}" if seg else e.commentary.strip()
        if seg:
            parts.append(seg)
    return " | ".join(_dedup_keep_order(parts))


def _first(values):
    for v in values:
        if v:
            return v
    return None


def aggregate(entities: list[RawEntity]):
    companies_raw: dict[str, list[RawEntity]] = {}
    people_raw: dict[str, list[RawEntity]] = {}
    links_raw: dict[str, list[RawEntity]] = {}

    for e in entities:
        if e.kind == "company":
            companies_raw.setdefault(normalize_name(e.name), []).append(e)
        elif e.kind == "person":
            people_raw.setdefault(normalize_name(e.name), []).append(e)
        elif e.kind == "link":
            key = (e.url or e.name).strip().lower()
            links_raw.setdefault(key, []).append(e)

    companies = [_make_company(g) for g in companies_raw.values()]
    companies.sort(key=lambda c: c.score, reverse=True)
    people = [_make_person(g) for g in people_raw.values()]
    links = [_make_link(g) for g in links_raw.values()]
    return companies, people, links


def _make_company(group: list[RawEntity]) -> Company:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    score = score_company(group_sorted)
    confidences = [e.confidence for e in group_sorted if e.confidence is not None]
    return Company(
        name=group_sorted[0].name,
        score=score,
        mentions=len(group_sorted),
        status=_status_from_score(score),
        signal=_build_signal(group_sorted),
        first_seen=group_sorted[0].source.timestamp,
        last_seen=group_sorted[-1].source.timestamp,
        sector=_first(e.sector for e in group_sorted),
        stage=_first(e.stage for e in group_sorted),
        financials=_first(e.financials for e in group_sorted),
        investors=_dedup_keep_order([i for e in group_sorted for i in e.investors]),
        sentiment=_first(e.sentiment for e in group_sorted),
        catalyst=_first(e.catalyst for e in group_sorted),
        risk=_first(e.risk for e in group_sorted),
        suggested_action=_first(e.suggested_action for e in group_sorted),
        confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        related_people=_dedup_keep_order(
            [p for e in group_sorted for p in e.related_people]),
        sources=[e.source for e in group_sorted],
    )


def _make_person(group: list[RawEntity]) -> Person:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    return Person(
        name=group_sorted[0].name,
        mentions=len(group_sorted),
        role=_first(e.role for e in group_sorted),
        affiliated_companies=_dedup_keep_order(
            [e.affiliated_company for e in group_sorted if e.affiliated_company]),
        notable_quotes=_dedup_keep_order(
            [e.quote for e in group_sorted if e.quote]),
        sources=[e.source for e in group_sorted],
    )


def _make_link(group: list[RawEntity]) -> Link:
    group_sorted = sorted(group, key=lambda e: e.source.timestamp)
    return Link(
        url=group_sorted[0].url or group_sorted[0].name,
        title=_first(e.title for e in group_sorted),
        shared_by=_dedup_keep_order([e.source.sender for e in group_sorted]),
        related_companies=_dedup_keep_order(
            [e.related_company for e in group_sorted if e.related_company]),
        first_seen=group_sorted[0].source.timestamp,
        sources=[e.source for e in group_sorted],
    )
