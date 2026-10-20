"""Background text-to-speech generation for parsed chapters.

Audio generation runs on a single daemon worker thread so uploads return
immediately and only one book is synthesized at a time. When TTS is disabled,
uploads still produce library/chapter data so the rest of the app can be
developed without external network calls.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import queue
import shutil
import threading

from . import database
from .config import AUDIO_DIR, TTS_ENABLED, TTS_VOICE


logger = logging.getLogger(__name__)
SYNTHESIS_TIMEOUT_SECONDS = 300
SYNTHESIS_ATTEMPTS = 3
SYNTHESIS_RETRY_SECONDS = 2

_pending: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def start() -> None:
    """Start the worker and requeue books left unfinished by a restart."""
    if not TTS_ENABLED:
        database.mark_audio_unavailable()
        return

    _ensure_worker()
    for book_id in database.recover_tts_queue():
        _pending.put(book_id)


def enqueue(book_id: str) -> None:
    """Queue a book for audio generation."""
    if not TTS_ENABLED:
        database.update_book_status(book_id, "unavailable")
        return

    _ensure_worker()
    database.update_book_status(book_id, "queued")
    _pending.put(book_id)


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="pubvox-tts", daemon=True)
        _worker.start()


def _worker_loop() -> None:
    while True:
        book_id = _pending.get()
        try:
            asyncio.run(_process_book(book_id))
        except Exception:
            logger.exception("TTS worker failed for book %s", book_id)
            try:
                database.mark_book_failed(book_id)
            except Exception:
                logger.exception("Unable to mark book %s failed", book_id)
        finally:
            _pending.task_done()


async def _process_book(book_id: str) -> None:
    """Generate audio files sequentially and persist per-chapter status."""
    if not database.book_exists(book_id):
        return

    database.update_book_status(book_id, "processing")
    chapters = database.queued_chapters(book_id)
    if not database.book_exists(book_id):
        return

    book_audio_dir = AUDIO_DIR / book_id
    book_audio_dir.mkdir(parents=True, exist_ok=True)

    for chapter in chapters:
        if not database.book_exists(book_id):
            return

        position = chapter["position"]
        output_path = book_audio_dir / f"{position:04d}.mp3"
        database.update_chapter_status(book_id=book_id, position=position, status="processing")

        try:
            await _synthesize(chapter["text"], output_path)
        except Exception:
            logger.exception("TTS generation failed for book %s chapter %s", book_id, position)
            database.update_chapter_status(book_id=book_id, position=position, status="failed")
            database.update_book_status(book_id, "failed")
            return

        if not database.book_exists(book_id):
            output_path.unlink(missing_ok=True)
            shutil.rmtree(book_audio_dir, ignore_errors=True)
            return

        database.update_chapter_status(
            book_id=book_id,
            position=position,
            status="ready",
            audio_path=output_path,
        )

    database.update_book_status(book_id, "ready")


async def _synthesize(text: str, output_path: Path) -> None:
    """Send one chapter's text to Edge TTS and save the resulting MP3."""
    import edge_tts  # type: ignore[reportMissingImports]

    for attempt in range(SYNTHESIS_ATTEMPTS):
        try:
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            await asyncio.wait_for(
                communicate.save(str(output_path)),
                timeout=SYNTHESIS_TIMEOUT_SECONDS,
            )
            return
        except Exception:
            output_path.unlink(missing_ok=True)
            if attempt == SYNTHESIS_ATTEMPTS - 1:
                raise
            await asyncio.sleep(SYNTHESIS_RETRY_SECONDS * (attempt + 1))
