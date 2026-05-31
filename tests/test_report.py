import os
import zipfile
from qun_alpha.models import Company, Person, Link, SourceRef
from qun_alpha import report


def _src():
    return SourceRef(group_name="AI投资群", sender="老王",
                     timestamp=1716700000, msg_id="m1")


def _sample():
    companies = [
        Company(name="IrisGo", score=72, mentions=3, status="emerging",
                signal="拿了$2.8M种子轮 · under-the-radar AI seed",
                first_seen=1716700000, last_seen=1716700050,
                sector="AI", stage="种子轮", financials="$2.8M 种子轮",
                investors=["AI Fund"], suggested_action="约创始人聊一次",
                confidence=0.8, related_people=["老王"], sources=[_src()]),
        Company(name="低分公司", score=10, mentions=1, status="noise",
                signal="一句带过", first_seen=1716700000, last_seen=1716700000,
                sources=[_src()]),
    ]
    people = [
        Person(name="老王", mentions=2, role="投资人",
               affiliated_companies=["AI Fund"],
               notable_quotes=["这个赛道还早"], sources=[_src()]),
    ]
    links = [
        Link(url="https://example.com/irisgo", title="IrisGo 报道",
             shared_by=["老王"], related_companies=["IrisGo"],
             first_seen=1716700000, sources=[_src()]),
    ]
    return companies, people, links


def test_build_markdown_contains_key_content():
    companies, people, links = _sample()
    md = report.build_markdown(companies, people, links)
    assert "IrisGo" in md
    assert "拿了$2.8M种子轮" in md
    assert "老王" in md
    assert "https://example.com/irisgo" in md
    assert md.index("IrisGo") < md.index("低分公司")


def test_write_reports_creates_both_files(tmp_path):
    companies, people, links = _sample()
    paths = report.write_reports(companies, people, links,
                                 out_dir=str(tmp_path), when="2026-05-31_120000")
    assert paths["md"] == os.path.join(str(tmp_path), "群聊投资机会_2026-05-31_120000.md")
    assert paths["docx"] == os.path.join(str(tmp_path), "群聊投资机会_2026-05-31_120000.docx")
    assert os.path.exists(paths["md"])
    assert os.path.exists(paths["docx"])
    assert "IrisGo" in open(paths["md"], encoding="utf-8").read()
    assert zipfile.is_zipfile(paths["docx"])
    with zipfile.ZipFile(paths["docx"]) as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
    assert "IrisGo" in doc_xml


def test_write_reports_default_dir_is_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    companies, people, links = _sample()
    paths = report.write_reports(companies, people, links, when="2026-05-31_120000")
    assert paths["md"].startswith(os.path.join(str(tmp_path), "Downloads"))
    assert os.path.exists(paths["md"])
