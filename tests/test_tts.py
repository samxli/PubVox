from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

import pytest

from pubvox import database, tts


def test_process_book_marks_chapters_ready(client, epub_path: Path, monkeypatch) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]

    async def fake_synthesize(_book_id: str, _text: str, output_path: Path) -> None:
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

    async def fail(_book_id: str, _text: str, _output_path: Path) -> None:
        raise RuntimeError("transient failure")

    monkeypatch.setattr(tts, "_synthesize", fail)
    asyncio.run(tts._process_book(book_id))

    failed = client.get(f"/api/books/{book_id}").json()
    assert failed["status"] == "failed"
    assert failed["chapters"][0]["status"] == "failed"
    assert book_id not in database.recover_tts_queue()

    async def succeed(_book_id: str, _text: str, output_path: Path) -> None:
        output_path.write_bytes(b"ID3")

    monkeypatch.setattr(tts, "_synthesize", succeed)
    asyncio.run(tts._process_book(book_id))

    ready = client.get(f"/api/books/{book_id}").json()
    assert ready["status"] == "ready"
    assert all(chapter["status"] == "ready" for chapter in ready["chapters"])


def test_enqueue_marks_book_queued(client, epub_path: Path, monkeypatch) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]
    assert client.get(f"/api/books/{book_id}").json()["status"] == "unavailable"

    queued: list[str] = []
    monkeypatch.setattr(tts, "TTS_ENABLED", True)
    monkeypatch.setattr(tts, "_ensure_worker", lambda: None)
    monkeypatch.setattr(tts._pending, "put", queued.append)
    tts.enqueue(book_id)

    assert queued == [book_id]
    assert client.get(f"/api/books/{book_id}").json()["status"] == "queued"


def test_start_marks_queued_books_unavailable_when_tts_disabled(
    client,
    epub_path: Path,
    monkeypatch,
) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]
    database.update_book_status(book_id, "queued")

    monkeypatch.setattr(tts, "TTS_ENABLED", False)
    tts.start()

    assert client.get(f"/api/books/{book_id}").json()["status"] == "unavailable"


def test_start_requeues_interrupted_books(client, epub_path: Path, monkeypatch) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]
    database.update_book_status(book_id, "queued")

    queued: list[str] = []
    monkeypatch.setattr(tts, "TTS_ENABLED", True)
    monkeypatch.setattr(tts, "_ensure_worker", lambda: None)
    monkeypatch.setattr(tts._pending, "put", queued.append)
    tts.start()

    assert book_id in queued


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
    monkeypatch.setattr(tts.database, "book_exists", lambda _book_id: True)

    output_path = tmp_path / "chapter.mp3"
    asyncio.run(tts._synthesize("book", "chapter text", output_path))

    assert calls == 2
    assert output_path.read_bytes() == b"ID3"


def test_synthesize_removes_partial_file_after_final_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FailingCommunicate:
        def __init__(self, _text: str, _voice: str) -> None:
            pass

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"partial")
            raise RuntimeError("permanent failure")

    fake_edge_tts = types.SimpleNamespace(Communicate=FailingCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)
    monkeypatch.setattr(tts, "SYNTHESIS_RETRY_SECONDS", 0)
    monkeypatch.setattr(tts.database, "book_exists", lambda _book_id: True)

    output_path = tmp_path / "chapter.mp3"
    with pytest.raises(RuntimeError, match="permanent failure"):
        asyncio.run(tts._synthesize("book", "chapter text", output_path))

    assert not output_path.exists()


def test_synthesize_stops_retrying_when_book_deleted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    class FailingCommunicate:
        def __init__(self, _text: str, _voice: str) -> None:
            pass

        async def save(self, path: str) -> None:
            nonlocal calls
            calls += 1
            Path(path).write_bytes(b"partial")
            raise RuntimeError("transient failure")

    fake_edge_tts = types.SimpleNamespace(Communicate=FailingCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)
    monkeypatch.setattr(tts, "SYNTHESIS_RETRY_SECONDS", 0)
    monkeypatch.setattr(tts.database, "book_exists", lambda _book_id: False)

    output_path = tmp_path / "chapter.mp3"
    asyncio.run(tts._synthesize("book", "chapter text", output_path))

    assert calls == 1
    assert not output_path.exists()
