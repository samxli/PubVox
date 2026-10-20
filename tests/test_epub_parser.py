from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT

from pubvox.epub_parser import (
    BR_TOKEN,
    _chapter_title,
    _extract_text,
    _reading_order,
    parse_epub,
)


def test_chapters_follow_spine_order(epub_path: Path) -> None:
    parsed = parse_epub(epub_path)

    titles = [chapter["title"] for chapter in parsed["chapters"]]
    assert titles == ["First Chapter", "Second Chapter"]


def test_paragraphs_are_preserved(epub_path: Path) -> None:
    text = parse_epub(epub_path)["chapters"][0]["text"]

    assert "First paragraph" in text
    assert "Second paragraph" in text
    assert "Inline tags need spacing." in text
    assert "library.\n\nSecond paragraph" in text
    assert "Line one\nLine two." in text
    assert "This stays joined." in text
    assert text.index("First paragraph") < text.index("Second paragraph")


def test_reading_order_skips_non_linear_and_keeps_repeats() -> None:
    chapter = SimpleNamespace(get_type=lambda: ITEM_DOCUMENT)
    appendix = SimpleNamespace(get_type=lambda: ITEM_DOCUMENT)

    class FakeBook:
        spine = [("chapter", "yes"), ("appendix", "no"), ("chapter", "yes")]

        @staticmethod
        def get_item_with_id(idref: str):
            return {"chapter": chapter, "appendix": appendix}[idref]

        @staticmethod
        def get_items_of_type(_item_type: str):
            return [chapter, appendix]

    assert _reading_order(FakeBook()) == [chapter, chapter]


def test_chapter_title_replaces_br_with_space() -> None:
    soup = BeautifulSoup("<h1>Chapter<br>One</h1>", "html.parser")

    title = _chapter_title(soup, "fallback.xhtml")

    assert title == "Chapter One"
    assert BR_TOKEN not in title


def test_chapter_title_ignores_extracted_body_tokens() -> None:
    soup = BeautifulSoup("<h1>Chapter<br>One</h1><p>Body text.</p>", "html.parser")
    _extract_text(soup)

    title = _chapter_title(soup, "fallback.xhtml")

    assert title == "Chapter One"
    assert BR_TOKEN not in title


def test_heading_line_breaks_survive_text_extraction() -> None:
    soup = BeautifulSoup("<h1>Chapter<br>One</h1><p>Body.</p>", "html.parser")

    title = _chapter_title(soup, "fallback.xhtml")
    text = _extract_text(soup)

    assert title == "Chapter One"
    assert "Chapter\nOne" in text
