"""Background text-to-speech generation for parsed chapters.

The first implementation uses FastAPI background tasks instead of a separate
queue service. When TTS is disabled, uploads still produce library/chapter data
so the rest of the app can be developed without external network calls.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from . import database
from .config import AUDIO_DIR, TTS_ENABLED, TTS_VOICE


logger = logging.getLogger(__name__)


def process_book(book_id: str) -> None:
    """Run chapter audio generation for a book when TTS is enabled."""
    if not TTS_ENABLED:
        database.update_book_status(book_id, "queued")
        return

    asyncio.run(_process_book(book_id))


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


async def _synthesize(text: str, output_path) -> None:
    """Send one chapter's text to Edge TTS and save the resulting MP3."""
    import edge_tts  # type: ignore[reportMissingImports]

    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(output_path))

