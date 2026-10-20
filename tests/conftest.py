"""Test bootstrapping and shared ePub fixtures."""

from __future__ import annotations

import os
import tempfile

os.environ["PUBVOX_DATA_DIR"] = tempfile.mkdtemp(prefix="pubvox-tests-")
os.environ.pop("PUBVOX_TTS_ENABLED", None)

from pathlib import Path

import pytest
from ebooklib import epub


def build_epub(path: Path) -> Path:
    """Write a small ePub whose manifest order differs from its spine order."""
    book = epub.EpubBook()
    book.set_identifier("pubvox-test")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    first = epub.EpubHtml(title="First", file_name="first.xhtml", lang="en")
    first.content = (
        "<html><body><h1>First Chapter</h1>"
        "<p>First paragraph has enough words to make this chapter long enough "
        "for extraction to keep it in the library.</p>"
        "<p>Second paragraph also has words so the parser should preserve both "
        "of them as separate paragraphs.</p>"
        "<p>Inline<strong>tags</strong> need spacing.</p>"
        "</body></html>"
    )
    second = epub.EpubHtml(title="Second", file_name="second.xhtml", lang="en")
    second.content = (
        "<html><body><h1>Second Chapter</h1>"
        "<p>Another paragraph with plenty of words to keep this chapter safely "
        "in the library list after parsing has finished completely.</p>"
        "</body></html>"
    )

    book.add_item(second)
    book.add_item(first)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [first, second]

    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def epub_path(tmp_path: Path) -> Path:
    return build_epub(tmp_path / "book.epub")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as test_client:
        yield test_client
