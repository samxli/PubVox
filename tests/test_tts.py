from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

from pubvox import tts


def test_process_book_marks_chapters_ready(client, epub_path: Path, monkeypatch) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]

    async def fake_synthesize(_text: str, output_path: Path) -> None:
        output_path.write_bytes(b"ID3")

    monkeypatch.setattr(tts, "_synthesize", fake_synthesize)
    asyncio.run(tts._process_book(book_id))

    book = client.get(f"/api/books/{book_id}").json()
    assert book["status"] == "ready"
    assert all(chapter["status"] == "ready" for chapter in book["chapters"])
    assert all(chapter["audioUrl"] for chapter in book["chapters"])

    audio = client.get(f"/api/books/{book_id}/chapters/0/audio")
    assert audio.status_code == 200
    assert audio.content == b"ID3"


def test_process_book_retries_failed_chapters(client, epub_path: Path, monkeypatch) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]

    async def fail(_text: str, _output_path: Path) -> None:
        raise RuntimeError("transient failure")

    monkeypatch.setattr(tts, "_synthesize", fail)
    asyncio.run(tts._process_book(book_id))

    failed = client.get(f"/api/books/{book_id}").json()
    assert failed["status"] == "failed"
    assert failed["chapters"][0]["status"] == "failed"

    async def succeed(_text: str, output_path: Path) -> None:
        output_path.write_bytes(b"ID3")

    monkeypatch.setattr(tts, "_synthesize", succeed)
    asyncio.run(tts._process_book(book_id))

    ready = client.get(f"/api/books/{book_id}").json()
    assert ready["status"] == "ready"
    assert all(chapter["status"] == "ready" for chapter in ready["chapters"])


def test_synthesize_retries_transient_errors(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    class FakeCommunicate:
        def __init__(self, _text: str, _voice: str) -> None:
            pass

        async def save(self, path: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                Path(path).write_bytes(b"partial")
                raise RuntimeError("transient failure")
            Path(path).write_bytes(b"ID3")

    fake_edge_tts = types.SimpleNamespace(Communicate=FakeCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)
    monkeypatch.setattr(tts, "SYNTHESIS_RETRY_SECONDS", 0)

    output_path = tmp_path / "chapter.mp3"
    asyncio.run(tts._synthesize("chapter text", output_path))

    assert calls == 2
    assert output_path.read_bytes() == b"ID3"
