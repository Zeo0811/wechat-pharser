import pytest
from pydantic import ValidationError
from qun_alpha.models import (
    Message, MessageChunk, SourceRef, RawEntity, Company, Person, Link,
)


def test_message_roundtrip():
    m = Message(
        msg_id="m1", group_id="g1", group_name="AI投资群",
        sender="老王", timestamp=1716700000, text="IrisGo 拿了 $2.8M 种子轮",
    )
    assert m.msg_type == "text"
    assert m.text.startswith("IrisGo")


def test_rawentity_kind_validated():
    src = SourceRef(group_name="AI投资群", sender="老王",
                    timestamp=1716700000, msg_id="m1")
    e = RawEntity(kind="company", name="IrisGo", quote="拿了$2.8M种子轮",
                  commentary="under-the-radar AI seed", source=src,
                  financials="$2.8M 种子轮", investors=["AI Fund"], confidence=0.8)
    assert e.kind == "company"
    assert e.investors == ["AI Fund"]
    with pytest.raises(ValidationError):
        RawEntity(kind="planet", name="x", source=src)


def test_company_defaults():
    c = Company(name="IrisGo", score=72, mentions=1, status="emerging",
                signal="拿了$2.8M种子轮 — under-the-radar AI seed",
                first_seen=1716700000, last_seen=1716700000, confidence=0.8)
    assert c.investors == []
    assert c.related_people == []
    assert c.sources == []
