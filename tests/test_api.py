from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from pubvox import database
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

        newer = client.post(
            f"/api/books/{book_id}/progress",
            json={"chapterIndex": 0, "elapsedSeconds": 45, "revision": 2},
        )
        stale = client.post(
            f"/api/books/{book_id}/progress",
            json={"chapterIndex": 0, "elapsedSeconds": 10, "revision": 1},
        )
        assert newer.status_code == 200
        assert stale.status_code == 200
        assert stale.json()["resume"]["elapsed_seconds"] == 45
        assert stale.json()["resume"]["revision"] == 2

        takeover = client.post(
            f"/api/books/{book_id}/progress",
            json={
                "chapterIndex": 0,
                "elapsedSeconds": 5,
                "revision": 1,
                "clientId": "other-device",
            },
        )
        assert takeover.status_code == 200
        assert takeover.json()["resume"]["elapsed_seconds"] == 5

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


def test_progress_uses_chapter_boundaries(client, epub_path: Path) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]
    durations = [chapter["durationSeconds"] for chapter in uploaded.json()["chapters"]]
    total_duration = sum(durations)
    expected = int((durations[0] / total_duration) * 100 + 0.5)

    boundary = client.post(
        f"/api/books/{book_id}/progress",
        json={"chapterIndex": 1, "elapsedSeconds": 0},
    )

    assert boundary.status_code == 200
    assert boundary.json()["progress"] == expected


def test_recover_tts_queue_resets_only_processing_books(client, epub_path: Path) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]
    database.update_book_status(book_id, "processing")
    database.update_chapter_status(book_id=book_id, position=0, status="processing")

    assert book_id in database.recover_tts_queue()
    recovered = client.get(f"/api/books/{book_id}").json()
    assert recovered["status"] == "queued"
    assert recovered["chapters"][0]["status"] == "queued"

    database.mark_book_failed(book_id)
    assert book_id not in database.recover_tts_queue()


def test_progress_rejects_stale_saves_per_client(client, epub_path: Path) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    book_id = uploaded.json()["id"]

    def save(client_id: str, revision: int, elapsed: float) -> dict:
        return client.post(
            f"/api/books/{book_id}/progress",
            json={
                "chapterIndex": 0,
                "elapsedSeconds": elapsed,
                "revision": revision,
                "clientId": client_id,
            },
        ).json()

    assert save("a", 10, 10)["resume"]["elapsed_seconds"] == 10
    assert save("b", 1, 20)["resume"]["elapsed_seconds"] == 20
    assert save("a", 9, 30)["resume"]["elapsed_seconds"] == 20
    assert save("a", 11, 40)["resume"]["elapsed_seconds"] == 40


def test_recover_tts_queue_includes_unavailable_books(client, epub_path: Path) -> None:
    with epub_path.open("rb") as handle:
        uploaded = client.post(
            "/api/books",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )

    assert uploaded.json()["status"] == "unavailable"
    assert uploaded.json()["id"] in database.recover_tts_queue()


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


def test_upload_rejects_chunked_oversized_body(monkeypatch) -> None:
    import main

    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1)
    monkeypatch.setattr(main, "UPLOAD_REQUEST_OVERHEAD_BYTES", 0)

    def body():
        yield (
            b'--xxx\r\nContent-Disposition: form-data; name="file"; '
            b'filename="book.epub"\r\n\r\nx\r\n--xxx--\r\n'
        )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/books",
            content=body(),
            headers={"content-type": "multipart/form-data; boundary=xxx"},
        )

    assert response.status_code == 413


def test_upload_rejects_oversized_content_length() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/books",
            content=b"",
            headers={"content-length": str(300 * 1024 * 1024)},
        )

    assert response.status_code == 413
