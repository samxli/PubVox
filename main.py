"""HTTP entry point for the PubVox monolith.

This module keeps the first product slice intentionally small: FastAPI serves the
static PWA, accepts ePub uploads, exposes library/progress APIs, and delegates
persistence, parsing, and TTS work to the package modules.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import re
from pathlib import Path
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pubvox import database, tts
from pubvox.config import AUDIO_DIR, STATIC_DIR, UPLOAD_DIR
from pubvox.epub_parser import parse_epub


STATIC_ROOT = STATIC_DIR.resolve()
STATIC_INDEX = STATIC_ROOT / "index.html"
ASSET_VERSION_PLACEHOLDER = "__PUBVOX_ASSET_VERSION__"
VERSIONED_ASSET_PATHS = (
    STATIC_ROOT / "styles.css",
    STATIC_ROOT / "app.js",
)
BOOK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local storage and SQLite tables before serving requests."""
    database.init_db()
    yield


app = FastAPI(title="PubVox", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ProgressUpdate(BaseModel):
    """Playback position reported by the browser during listening."""

    chapterIndex: int = Field(ge=0)
    elapsedSeconds: float = Field(ge=0)
    progressPercent: int = Field(ge=0, le=100)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a lightweight readiness response for smoke checks."""
    return {"status": "ok"}


@app.get("/api/books")
def books() -> list[dict]:
    """List the current local user's library with chapter and resume data."""
    return database.list_books()


@app.post("/api/books", status_code=201)
def upload_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    """Store an uploaded ePub, parse its chapters, and queue audio generation."""
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Please upload an .epub file.")

    book_id = uuid.uuid4().hex
    destination = UPLOAD_DIR / f"{book_id}.epub"

    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    try:
        parsed = parse_epub(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    book = database.create_book(
        book_id=book_id,
        title=str(parsed["title"]),
        author=str(parsed["author"]),
        filename=file.filename,
        chapters=list(parsed["chapters"]),
    )
    background_tasks.add_task(tts.process_book, book_id)
    return book


@app.get("/api/books/{book_id}")
def book(book_id: str) -> dict:
    """Return a single book payload for the current local user."""
    found = database.get_book(book_id)
    if not found:
        raise HTTPException(status_code=404, detail="Book not found.")
    return found


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str) -> dict[str, bool]:
    """Remove a book from the library and delete its stored artifacts."""
    if not BOOK_ID_PATTERN.fullmatch(book_id):
        raise HTTPException(status_code=404, detail="Book not found.")

    deleted_book_id = database.delete_book(book_id)
    if not deleted_book_id:
        raise HTTPException(status_code=404, detail="Book not found.")

    remove_book_files(deleted_book_id)
    return {"deleted": True}


@app.post("/api/books/{book_id}/progress")
def save_progress(book_id: str, progress: ProgressUpdate) -> dict:
    """Persist listening progress so reloads and other devices can resume."""
    updated = database.update_progress(
        book_id=book_id,
        chapter_index=progress.chapterIndex,
        elapsed_seconds=progress.elapsedSeconds,
        progress_percent=progress.progressPercent,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Book not found.")
    return updated


@app.get("/api/books/{book_id}/chapters/{position}/audio")
def chapter_audio(book_id: str, position: int) -> FileResponse:
    """Stream a generated chapter MP3 once the TTS pipeline marks it ready."""
    chapter = database.get_chapter(book_id, position)
    if not chapter or chapter["status"] != "ready" or not chapter["audio_path"]:
        raise HTTPException(status_code=404, detail="Audio is not ready for this chapter.")

    audio_path = Path(chapter["audio_path"])
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file is missing.")

    return FileResponse(audio_path, media_type="audio/mpeg", filename=audio_path.name)


def remove_book_files(book_id: str) -> None:
    """Best-effort cleanup for uploaded ePub and generated chapter audio."""
    try:
        upload_path, audio_dir = book_artifact_paths(book_id)
    except ValueError:
        logger.warning("Skipping artifact cleanup for invalid book ID %s", book_id, exc_info=True)
        return

    try:
        upload_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Unable to delete uploaded ePub for book %s", book_id, exc_info=True)

    if audio_dir.exists():
        try:
            shutil.rmtree(audio_dir)
        except OSError:
            logger.warning("Unable to delete audio directory for book %s", book_id, exc_info=True)


def book_artifact_paths(book_id: str) -> tuple[Path, Path]:
    """Return validated artifact paths for a server-generated book ID."""
    if not BOOK_ID_PATTERN.fullmatch(book_id):
        raise ValueError("invalid book id")

    upload_root = UPLOAD_DIR.resolve()
    audio_root = AUDIO_DIR.resolve()
    upload_path = (upload_root / f"{book_id}.epub").resolve()
    audio_dir = (audio_root / book_id).resolve()
    require_child_path(upload_path, upload_root)
    require_child_path(audio_dir, audio_root)
    return upload_path, audio_dir


def require_child_path(path: Path, root: Path) -> None:
    """Ensure a resolved path is contained by its resolved storage root."""
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes storage root: {path}") from exc


@app.get("/")
def index() -> HTMLResponse:
    """Serve the PWA shell."""
    return pwa_shell()


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    """Serve the web app manifest from the static bundle."""
    return FileResponse(STATIC_ROOT / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/{path:path}", include_in_schema=False)
def static_fallback(path: str) -> HTMLResponse:
    """Fall back to the PWA shell for browser routes outside the API."""
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found.")

    return pwa_shell()


def pwa_shell() -> HTMLResponse:
    """Serve the HTML shell with a cache token matching current static assets."""
    html = STATIC_INDEX.read_text(encoding="utf-8").replace(
        ASSET_VERSION_PLACEHOLDER,
        static_asset_version(),
    )
    return HTMLResponse(html)


def static_asset_version() -> str:
    """Return a stable token that changes whenever bundled CSS or JS changes."""
    return str(max(path.stat().st_mtime_ns for path in VERSIONED_ASSET_PATHS))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

