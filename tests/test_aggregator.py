from qun_alpha.models import RawEntity, SourceRef
from qun_alpha.aggregator import aggregate, score_company, normalize_name


def _src(sender="老王", ts=1716700000, mid="m1", group="AI投资群"):
    return SourceRef(group_name=group, sender=sender, timestamp=ts, msg_id=mid)


def test_normalize_name():
    assert normalize_name(" IrisGo ") == "irisgo"
    assert normalize_name("Iris Go") == "irisgo"
    assert normalize_name("锦秋基金") == "锦秋基金"


def test_dedup_companies_across_chunks():
    ents = [
        RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮",
                  commentary="under-the-radar AI seed", source=_src(mid="m1"),
                  financials="$2.8M 种子轮", investors=["AI Fund"], confidence=0.8),
        RawEntity(kind="company", name="iris go", quote="A轮在谈",
                  commentary="持续融资", source=_src(ts=1716786400, mid="m9"),
                  investors=["拾象"], confidence=0.6),
    ]
    companies, people, links = aggregate(ents)
    assert len(companies) == 1
    c = companies[0]
    assert c.name == "IrisGo"               # 保留首个出现的原始写法
    assert c.mentions == 2
    assert set(c.investors) == {"AI Fund", "拾象"}
    assert c.first_seen == 1716700000
    assert c.last_seen == 1716786400
    assert "$2.8M" in c.signal
    assert len(c.sources) == 2


def test_score_rises_with_signal_richness():
    poor = RawEntity(kind="company", name="X", source=_src(), confidence=0.1)
    rich = RawEntity(kind="company", name="Y", quote="2-3亿美金估值",
                     commentary="investors actively tracking paid-acquisition strategy",
                     source=_src(), financials="2-3亿美金", investors=["字节", "拾象"],
                     confidence=0.9)
    assert score_company([rich]) > score_company([poor])


def test_status_noise_for_thin_signal():
    thin = [RawEntity(kind="company", name="路人公司", source=_src(), confidence=0.0)]
    companies, _, _ = aggregate(thin)
    assert companies[0].status == "noise"


def test_status_emerging_for_strong_signal():
    strong = [RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮，AI Fund领投",
                        commentary="exactly the under-the-radar AI seed worth chasing",
                        source=_src(), financials="$2.8M 种子轮",
                        investors=["AI Fund"], confidence=0.85)]
    companies, _, _ = aggregate(strong)
    assert companies[0].status == "emerging"


def test_people_and_links_separated():
    ents = [
        RawEntity(kind="person", name="梦琪", role="创始人",
                  affiliated_company="invoko.ai", quote="一个AI创始人",
                  source=_src(sender="小李", mid="p1")),
        RawEntity(kind="link", name="42章经播客", url="https://example.com/42",
                  title="profiling founder 梦琪", related_company="invoko.ai",
                  source=_src(sender="小李", mid="l1")),
    ]
    companies, people, links = aggregate(ents)
    assert len(companies) == 0
    assert len(people) == 1 and people[0].name == "梦琪"
    assert people[0].affiliated_companies == ["invoko.ai"]
    assert len(links) == 1 and links[0].url == "https://example.com/42"
    assert links[0].related_companies == ["invoko.ai"]


def test_companies_sorted_by_score_desc():
    ents = [
        RawEntity(kind="company", name="Weak", source=_src(mid="a"), confidence=0.1),
        RawEntity(kind="company", name="Strong", quote="$10M ARR",
                  commentary="specific revenue milestone worth chasing",
                  source=_src(mid="b"), financials="$10M ARR",
                  investors=["拾象"], confidence=0.9),
    ]
    companies, _, _ = aggregate(ents)
    assert [c.name for c in companies] == ["Strong", "Weak"]
