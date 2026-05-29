from pathlib import Path

HTML = Path("landing/index.html").read_text(encoding="utf-8")


def test_landing_has_all_steps_and_theme():
    assert "wechat-decrypt" in HTML
    assert "qun-alpha serve" in HTML
    assert "import-export" in HTML
    assert "--accent" in HTML
    assert HTML.count('class="step"') >= 6
    assert "themeToggle" in HTML
