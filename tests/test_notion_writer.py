from qun_alpha.models import Company, SourceRef
from qun_alpha.notion_writer import company_to_properties, write_companies


def _company(name="IrisGo", score=72, status="emerging"):
    return Company(
        name=name, score=score, mentions=2, status=status,
        signal="拿了$2.8M种子轮 — under-the-radar AI seed",
        first_seen=1716700000, last_seen=1716786400,
        sector="AI", stage="种子", financials="$2.8M 种子轮",
        investors=["AI Fund", "拾象"], confidence=0.8,
        sources=[SourceRef(group_name="AI投资群", sender="老王",
                           timestamp=1716700000, msg_id="m1")],
    )


def test_company_to_properties_maps_fields():
    props = company_to_properties(_company())
    assert props["Company"]["title"][0]["text"]["content"] == "IrisGo"
    assert props["Score"]["number"] == 72
    assert props["Status"]["select"]["name"] == "emerging"
    assert props["Mntns"]["number"] == 2
    assert "拿了$2.8M" in props["Signal"]["rich_text"][0]["text"]["content"]


def test_write_companies_dry_run_does_not_call_api():
    class BoomClient:
        class pages:
            @staticmethod
            def create(**kw):
                raise AssertionError("dry_run 不应调用 API")
    payloads = write_companies([_company()], client=BoomClient(),
                               database_id="db1", dry_run=True)
    assert len(payloads) == 1
    assert payloads[0]["parent"]["database_id"] == "db1"


def test_write_companies_calls_create():
    created = []
    class FakeClient:
        class pages:
            @staticmethod
            def create(**kw):
                created.append(kw)
                return {"id": "newpage"}
    out = write_companies([_company()], client=FakeClient(),
                          database_id="db1", dry_run=False)
    assert len(created) == 1
    assert created[0]["parent"]["database_id"] == "db1"
    assert out == ["newpage"]
