"""Runtime configuration for local storage, static assets, and TTS behavior."""

from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("PUBVOX_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "app.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_USER_ID = 1
TTS_ENABLED = os.getenv("PUBVOX_TTS_ENABLED", "").lower() in {"1", "true", "yes", "on"}
TTS_VOICE = os.getenv("PUBVOX_TTS_VOICE", "en-US-AriaNeural")

