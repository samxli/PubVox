"""HTTP entry point for the PubVox monolith.

This module keeps the first product slice intentionally small: FastAPI serves the
static PWA, accepts ePub uploads, exposes library/progress APIs, and delegates
persistence, parsing, and TTS work to the package modules.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pubvox import database, tts
from pubvox.config import STATIC_DIR, UPLOAD_DIR
from pubvox.epub_parser import parse_epub


STATIC_ROOT = STATIC_DIR.resolve()


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


@app.get("/")
def index() -> FileResponse:
    """Serve the PWA shell."""
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    """Serve the web app manifest from the static bundle."""
    return FileResponse(STATIC_ROOT / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/{path:path}", include_in_schema=False)
def static_fallback(path: str) -> FileResponse:
    """Fall back to the PWA shell for browser routes outside the API."""
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found.")

    return FileResponse(STATIC_ROOT / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

