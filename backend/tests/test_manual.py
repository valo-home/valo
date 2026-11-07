import json
import pathlib
import re

import pytest

from app.domain import manual
from app.lib.errors import ApplicationError

DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs"


@pytest.fixture
def tree(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    (tmp_path / "ru").mkdir()
    (tmp_path / "en").mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"key": "a", "title": {"ru": "Раздел", "en": "Section"}, "pages": ["one", "two", "gone"]},
                    {"key": "b", "title": {"en": "Empty"}, "pages": ["gone"]},
                ]
            }
        ),
        "utf-8",
    )
    (tmp_path / "ru" / "one.md").write_text("# Первая\n\nТекст", "utf-8")
    (tmp_path / "en" / "one.md").write_text("# First\n\nText", "utf-8")
    (tmp_path / "en" / "two.md").write_text("No title", "utf-8")
    monkeypatch.setattr(manual, "HELP_DIR", tmp_path)
    return tmp_path


def test_index_uses_language_and_fallback(tree: pathlib.Path) -> None:
    ru = manual.index("ru")
    assert [s["title"] for s in ru["sections"]] == ["Раздел"]
    assert ru["sections"][0]["pages"] == [{"slug": "one", "title": "Первая"}, {"slug": "two", "title": "two"}]
    assert manual.index("de")["sections"][0]["title"] == "Section"
    assert manual.index("de")["sections"][0]["pages"][0]["title"] == "First"


def test_page_fallback_and_bad_slugs(tree: pathlib.Path) -> None:
    assert manual.page("two", "ru") == {"slug": "two", "lang": "en", "title": "two", "text": "No title"}
    assert manual.page("one", "uk")["lang"] == "en"
    for bad in ("gone", "../index", "One", "a/b", ""):
        with pytest.raises(ApplicationError):
            manual.page(bad, "ru")


def test_missing_index_gives_empty_sections(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manual, "HELP_DIR", tmp_path / "nope")
    assert manual.index("ru")["sections"] == []
    assert manual.files() == []


def test_search_ranks_title_and_strips_markup(tree: pathlib.Path) -> None:
    (tree / "ru" / "two.md").write_text("# Сцены\n\nСцена **запоминает** [состояние](/docs/one) устройств", "utf-8")
    hits = manual.search("сцена состояние", "ru")
    assert hits[0]["slug"] == "two" and hits[0]["text"] == "Сцена запоминает состояние устройств"
    assert manual.search("  ", "ru") == []
    assert manual.search("нет такого", "ru") == []


def test_product_docs_are_complete_and_follow_the_style() -> None:
    index = json.loads((DOCS / "index.json").read_text("utf-8"))
    slugs = {slug for sec in index["sections"] for slug in sec["pages"]}
    for slug in slugs:
        langs = ("ru",) if slug == "architecture" else ("ru", "uk", "en")
        for lang in langs:
            f = DOCS / lang / f"{slug}.md"
            assert f.is_file(), f
            text = f.read_text("utf-8")
            assert text.startswith("# "), f
            assert "ё" not in text and "—" not in text, f
            for link in re.findall(r"\]\((/docs/[^)#\s]*)", text):
                assert link.removeprefix("/docs/") in slugs, (f, link)
            prose = re.sub(r"```.*?```", "", text, flags=re.S)
            assert not [x for x in prose.splitlines() if x.rstrip().endswith(":")], f
