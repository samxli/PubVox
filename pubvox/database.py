"""SQLite persistence helpers for PubVox.

The database layer returns JSON-ready dictionaries shaped for the frontend API,
so route handlers can stay thin while SQLite details remain centralized here.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .config import AUDIO_DIR, DATA_DIR, DEFAULT_USER_ID, DB_PATH, UPLOAD_DIR


def utc_now() -> str:
    """Return a timezone-aware timestamp suitable for SQLite text columns."""
    return datetime.now(timezone.utc).isoformat()


def ensure_storage() -> None:
    """Create the mounted data, upload, and generated-audio directories."""
    for path in (DATA_DIR, UPLOAD_DIR, AUDIO_DIR):
        path.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect() -> Iterable[sqlite3.Connection]:
    """Open a SQLite connection with row dictionaries and foreign keys enabled."""
    ensure_storage()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """Create tables and seed the single local user used by the first app slice."""
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                current_chapter INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                audio_path TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, position)
            );

            CREATE TABLE IF NOT EXISTS progress (
                book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
                chapter_index INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO users (id, username, display_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (DEFAULT_USER_ID, "local", "Local library", utc_now()),
        )


def create_book(
    *,
    book_id: str,
    title: str,
    author: str,
    filename: str,
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Insert a parsed ePub and its chapter records, returning its API payload."""
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO books (
                id, user_id, title, author, filename, status, progress,
                current_chapter, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                DEFAULT_USER_ID,
                title,
                author,
                filename,
                "queued",
                0,
                0,
                now,
                now,
            ),
        )
        for position, chapter in enumerate(chapters):
            connection.execute(
                """
                INSERT INTO chapters (
                    id, book_id, position, title, text, duration_seconds,
                    audio_path, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{book_id}-{position}",
                    book_id,
                    position,
                    chapter["title"],
                    chapter["text"],
                    chapter["duration_seconds"],
                    None,
                    "queued",
                    now,
                    now,
                ),
            )
        return _book_payload(connection, _book_row(connection, book_id))


def list_books() -> list[dict[str, Any]]:
    """Return all books for the local user, newest activity first."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM books
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (DEFAULT_USER_ID,),
        ).fetchall()
        return [_book_payload(connection, row) for row in rows]


def get_book(book_id: str) -> dict[str, Any] | None:
    """Return one book with chapters and resume data, or None when missing."""
    with connect() as connection:
        row = _book_row(connection, book_id)
        return _book_payload(connection, row) if row else None


def book_exists(book_id: str) -> bool:
    """Return whether a book still exists for the local user."""
    with connect() as connection:
        return _book_row(connection, book_id) is not None


def delete_book(book_id: str) -> str | None:
    """Delete a book and return its stored ID after cascading related records."""
    with connect() as connection:
        row = _book_row(connection, book_id)
        if not row:
            return None

        deleted_book_id = str(row["id"])

        connection.execute(
            """
            DELETE FROM books
            WHERE id = ? AND user_id = ?
            """,
            (book_id, DEFAULT_USER_ID),
        )
        return deleted_book_id


def get_chapter(book_id: str, position: int) -> dict[str, Any] | None:
    """Return a raw chapter row by book and zero-based chapter position."""
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM chapters
            WHERE book_id = ? AND position = ?
            """,
            (book_id, position),
        ).fetchone()
        return dict(row) if row else None


def queued_chapters(book_id: str) -> list[dict[str, Any]]:
    """Return chapters that should be attempted by the TTS worker."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM chapters
            WHERE book_id = ? AND status IN ('queued', 'failed')
            ORDER BY position ASC
            """,
            (book_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_book_status(book_id: str, status: str) -> None:
    """Move a book through queued, processing, ready, or failed states."""
    with connect() as connection:
        connection.execute(
            """
            UPDATE books
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, utc_now(), book_id),
        )


def update_chapter_status(
    *,
    book_id: str,
    position: int,
    status: str,
    audio_path: Path | None = None,
) -> None:
    """Update TTS status for one chapter and optionally persist its audio path."""
    with connect() as connection:
        connection.execute(
            """
            UPDATE chapters
            SET status = ?, audio_path = COALESCE(?, audio_path), updated_at = ?
            WHERE book_id = ? AND position = ?
            """,
            (status, str(audio_path) if audio_path else None, utc_now(), book_id, position),
        )


def update_progress(
    *,
    book_id: str,
    chapter_index: int,
    elapsed_seconds: float,
    progress_percent: int,
) -> dict[str, Any] | None:
    """Persist resume state and denormalized whole-book progress."""
    now = utc_now()
    with connect() as connection:
        row = _book_row(connection, book_id)
        if not row:
            return None

        connection.execute(
            """
            UPDATE books
            SET current_chapter = ?, progress = ?, updated_at = ?
            WHERE id = ?
            """,
            (chapter_index, progress_percent, now, book_id),
        )
        connection.execute(
            """
            INSERT INTO progress (book_id, chapter_index, elapsed_seconds, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                chapter_index = excluded.chapter_index,
                elapsed_seconds = excluded.elapsed_seconds,
                updated_at = excluded.updated_at
            """,
            (book_id, chapter_index, elapsed_seconds, now),
        )
        return _book_payload(connection, _book_row(connection, book_id))


def _book_row(connection: sqlite3.Connection, book_id: str) -> sqlite3.Row | None:
    """Fetch a book row scoped to the local user."""
    return connection.execute(
        """
        SELECT * FROM books
        WHERE id = ? AND user_id = ?
        """,
        (book_id, DEFAULT_USER_ID),
    ).fetchone()


def _book_payload(connection: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any]:
    """Convert book, chapter, and resume rows into the public API shape."""
    if row is None:
        raise ValueError("book row is required")

    chapter_rows = connection.execute(
        """
        SELECT * FROM chapters
        WHERE book_id = ?
        ORDER BY position ASC
        """,
        (row["id"],),
    ).fetchall()
    progress = connection.execute(
        """
        SELECT chapter_index, elapsed_seconds, updated_at
        FROM progress
        WHERE book_id = ?
        """,
        (row["id"],),
    ).fetchone()

    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "filename": row["filename"],
        "status": row["status"],
        "progress": row["progress"],
        "currentChapter": row["current_chapter"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "resume": dict(progress) if progress else None,
        "chapters": [_chapter_payload(chapter) for chapter in chapter_rows],
    }


def _chapter_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a chapter row into the frontend contract."""
    audio_url = None
    if row["audio_path"] and row["status"] == "ready":
        audio_url = f"/api/books/{row['book_id']}/chapters/{row['position']}/audio"

    return {
        "id": row["id"],
        "position": row["position"],
        "title": row["title"],
        "durationSeconds": row["duration_seconds"],
        "status": row["status"],
        "ready": row["status"] == "ready",
        "audioUrl": audio_url,
    }

