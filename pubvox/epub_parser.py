"""ePub metadata and chapter extraction.

The parser converts an uploaded ePub into a compact structure the database layer
can store immediately, while estimating chapter durations until real audio files
exist.
"""

from __future__ import annotations

from pathlib import Path
import re

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub


WORDS_PER_MINUTE = 165


def parse_epub(file_path: Path) -> dict[str, object]:
    """Read an ePub file and return title, author, and chapter text records."""
    book = epub.read_epub(str(file_path))
    chapters = _extract_chapters(book)

    if not chapters:
        raise ValueError("No readable chapter text was found in this ePub.")

    return {
        "title": _metadata_value(book, "title") or file_path.stem,
        "author": _metadata_value(book, "creator") or "Unknown author",
        "chapters": chapters,
    }


def _metadata_value(book: epub.EpubBook, key: str) -> str | None:
    """Return the first cleaned Dublin Core metadata value for a key."""
    values = book.get_metadata("DC", key)
    if not values:
        return None
    return _clean_text(values[0][0])


def _extract_chapters(book: epub.EpubBook) -> list[dict[str, object]]:
    """Extract readable document items as ordered chapter records."""
    chapters: list[dict[str, object]] = []
    short_sections: list[dict[str, object]] = []

    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()

        text = _clean_text(soup.get_text("\n"))
        if not text:
            continue

        chapter = {
            "title": _chapter_title(soup, item.get_name()),
            "text": text,
            "duration_seconds": _estimate_duration_seconds(text),
        }

        if len(text.split()) >= 20:
            chapters.append(chapter)
        else:
            short_sections.append(chapter)

    return chapters or short_sections


def _chapter_title(soup: BeautifulSoup, fallback: str) -> str:
    """Prefer the first heading for a chapter title, then fall back to filename."""
    heading = soup.find(["h1", "h2", "h3"])
    if heading:
        title = _clean_text(heading.get_text(" "))
        if title:
            return title

    stem = Path(fallback).stem.replace("_", " ").replace("-", " ")
    return stem.title() or "Untitled chapter"


def _clean_text(value: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        re.sub(r"[ \t]+", " ", paragraph.replace("\n", " ")).strip()
        for paragraph in re.split(r"\n\s*\n+", normalized)
    ]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _estimate_duration_seconds(text: str) -> int:
    """Estimate narration length from word count until TTS metadata is available."""
    word_count = max(1, len(text.split()))
    return max(30, round((word_count / WORDS_PER_MINUTE) * 60))

