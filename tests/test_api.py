from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from pubvox.config import UPLOAD_DIR


def test_upload_progress_and_delete(epub_path: Path) -> None:
    with TestClient(app) as client:
        with epub_path.open("rb") as handle:
            uploaded = client.post(
                "/api/books",
                files={"file": ("book.epub", handle, "application/epub+zip")},
            )

        assert uploaded.status_code == 201
        book = uploaded.json()
        book_id = book["id"]
        assert book["title"] == "Test Book"
        assert book["status"] == "unavailable"
        assert [chapter["title"] for chapter in book["chapters"]] == [
            "First Chapter",
            "Second Chapter",
        ]

        invalid = client.post(
            f"/api/books/{book_id}/progress",
            json={"chapterIndex": 99, "elapsedSeconds": 5},
        )
        assert invalid.status_code == 404

        saved = client.post(
            f"/api/books/{book_id}/progress",
            json={"chapterIndex": 0, "elapsedSeconds": 30},
        )
        assert saved.status_code == 200
        payload = saved.json()
        assert payload["currentChapter"] == 0
        assert 0 <= payload["progress"] <= 100
        assert payload["resume"]["elapsed_seconds"] == 30

        missing_audio = client.get(f"/api/books/{book_id}/chapters/0/audio")
        assert missing_audio.status_code == 404

        retry = client.post(f"/api/books/{book_id}/tts")
        assert retry.status_code == 409

        deleted = client.delete(f"/api/books/{book_id}")
        assert deleted.status_code == 200
        assert not (UPLOAD_DIR / f"{book_id}.epub").exists()
        assert client.get(f"/api/books/{book_id}").status_code == 404


def test_upload_rejects_non_epub() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/books",
            files={"file": ("notes.txt", b"not an epub", "text/plain")},
        )

    assert response.status_code == 400


def test_upload_rejects_oversized_file(epub_path: Path, monkeypatch) -> None:
    import main

    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1)

    with TestClient(main.app) as client:
        with epub_path.open("rb") as handle:
            response = client.post(
                "/api/books",
                files={"file": ("book.epub", handle, "application/epub+zip")},
            )

    assert response.status_code == 413
