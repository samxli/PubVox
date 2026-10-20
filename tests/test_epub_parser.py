from __future__ import annotations

from pathlib import Path

from pubvox.epub_parser import parse_epub


def test_chapters_follow_spine_order(epub_path: Path) -> None:
    parsed = parse_epub(epub_path)

    titles = [chapter["title"] for chapter in parsed["chapters"]]
    assert titles == ["First Chapter", "Second Chapter"]


def test_paragraphs_are_preserved(epub_path: Path) -> None:
    text = parse_epub(epub_path)["chapters"][0]["text"]

    assert "First paragraph" in text
    assert "Second paragraph" in text
    assert "Inline tags need spacing." in text
    assert text.index("First paragraph") < text.index("Second paragraph")
    assert "\n\n" in text
