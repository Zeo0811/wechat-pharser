from qun_alpha.models import Company, Person, SourceRef
from qun_alpha.notion_writer import company_to_properties, write_companies, person_to_properties, write_people


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


class _Pages:
    def __init__(self, store):
        self._store = store
    def create(self, **kw):
        self._store["created"].append(kw)
        return {"id": "newpage"}
    def update(self, **kw):
        self._store["updated"].append(kw)
        return {"id": kw["page_id"]}


class _Databases:
    def __init__(self, existing_id):
        self._existing_id = existing_id
        self.queries = []
    def query(self, **kw):
        self.queries.append(kw)
        if self._existing_id:
            return {"results": [{"id": self._existing_id}]}
        return {"results": []}


class FakeClient:
    """existing_id=None → 库里没有，应走 create；否则走 update。"""
    def __init__(self, existing_id=None):
        self._store = {"created": [], "updated": []}
        self.pages = _Pages(self._store)
        self.databases = _Databases(existing_id)
    @property
    def created(self):
        return self._store["created"]
    @property
    def updated(self):
        return self._store["updated"]


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
        class databases:
            @staticmethod
            def query(**kw):
                raise AssertionError("dry_run 不应调用 API")
    payloads = write_companies([_company()], client=BoomClient(),
                               database_id="db1", dry_run=True)
    assert len(payloads) == 1
    assert payloads[0]["parent"]["database_id"] == "db1"


def test_write_companies_creates_when_absent():
    client = FakeClient(existing_id=None)
    out = write_companies([_company()], client=client,
                          database_id="db1", dry_run=False)
    assert len(client.created) == 1
    assert client.created[0]["parent"]["database_id"] == "db1"
    assert client.updated == []
    assert out == ["newpage"]
    assert client.databases.queries[0]["database_id"] == "db1"


def test_write_companies_updates_when_present():
    client = FakeClient(existing_id="oldpage")
    out = write_companies([_company()], client=client,
                          database_id="db1", dry_run=False)
    assert client.created == []
    assert len(client.updated) == 1
    assert client.updated[0]["page_id"] == "oldpage"
    assert out == ["oldpage"]


def _person():
    return Person(
        name="梦琪", mentions=2, role="创始人",
        affiliated_companies=["invoko.ai"],
        notable_quotes=["一个AI创始人", "虚荣心、装"],
        sources=[SourceRef(group_name="AI投资群", sender="小李",
                           timestamp=1716700000, msg_id="p1")],
    )


def test_person_to_properties_maps_fields():
    props = person_to_properties(_person())
    assert props["Person"]["title"][0]["text"]["content"] == "梦琪"
    assert props["Mntns"]["number"] == 2
    assert props["Role"]["rich_text"][0]["text"]["content"] == "创始人"
    assert props["Affiliated"]["multi_select"][0]["name"] == "invoko.ai"
    assert "一个AI创始人" in props["Quotes"]["rich_text"][0]["text"]["content"]


def test_write_people_creates_when_absent():
    client = FakeClient(existing_id=None)
    out = write_people([_person()], client=client,
                       database_id="pdb", dry_run=False)
    assert len(client.created) == 1
    assert out == ["newpage"]


def test_write_people_dry_run():
    payloads = write_people([_person()], client=None,
                            database_id="pdb", dry_run=True)
    assert payloads[0]["parent"]["database_id"] == "pdb"
    assert payloads[0]["properties"]["Person"]["title"][0]["text"]["content"] == "梦琪"
