# PubVox - ePub to Audiobook Web App Architecture

## 1. System Overview

This project is an ultra-lightweight, open-source web application that converts ePub files into streamable audiobooks. Designed for simplicity and easy deployment on small VPS instances or local desktops via Docker, it features in-app playback, cross-device progress tracking, and background playback capabilities.

## 2. High-Level Architecture

To prioritize simplicity and minimize the footprint, the system uses a **Monolithic Architecture** contained within a single Docker container. It avoids heavy message brokers and external database servers.

- **Frontend:** A lightweight Progressive Web App (PWA) using Vanilla JavaScript / Alpine.js for playback and OS integration.
- **Backend:** A single Python web server handling APIs, ePub parsing, and asynchronous TTS generation.
- **Database & Storage:** SQLite for relational data and local file storage for media.
- **TTS Engine:** Edge TTS (Microsoft Edge Read Aloud API wrapper) to ensure it runs comfortably on low-resource environments.

---

## 3. Component Details

### 3.1. Frontend (Lightweight PWA)

- **Tech Stack:** Vanilla JavaScript/HTML5 with Alpine.js, served directly by the backend to avoid complex build steps.
- **Audio Playback:** Standard HTML5 `<audio>` element. 
- **Car & Screen-Off Support:** Integrates the **Media Session API**. This is the critical component that allows mobile operating systems (iOS/Android) and car Bluetooth systems to control playback (play, pause, skip) while the device screen is off.
- **In-App Only:** No download buttons are exposed; the UI acts purely as a streaming player.
- **Progress Tracking:** A JavaScript interval periodically sends lightweight `POST` requests to the backend with the current audiobook timestamp.

### 3.2. Backend & TTS Processing (Python Monolith)

- **Framework:** FastAPI (Python). Python is ideal for handling ePub extraction and TTS libraries.
- **Authentication:** Simple session-based auth or lightweight JWT tokens.
- **ePub Processing:**
  - Uploaded `.epub` files are parsed using libraries like `EbookLib` and `BeautifulSoup`.
  - Text is logically split into chapters.
- **TTS Generation (Edge TTS):** A background thread (using native Python `asyncio` or `concurrent.futures`, avoiding heavy queues like Celery/Redis) processes chapters sequentially.
  - `edge-tts` is utilized to generate high-quality audio without requiring heavy local GPU/CPU compute, making it perfect for a small VPS.
- **Audio Serving:** The backend serves the generated audio chunks dynamically to the frontend player.

### 3.3. Database and Storage

- **Database:** **SQLite**. A single `app.db` file stored on a persistent Docker volume.
  - `Users` table: Basic credentials.
  - `Books` table: Metadata (title, author) mapped to a user.
  - `Progress` table: Current chapter and timestamp for seamless resume.
- **File Storage:** Local filesystem storage (within a mounted Docker volume) for:
  - Uploaded raw ePub files.
  - Generated audio chunks (e.g., `.mp3` files per chapter).

---

## 4. Workflows

1. **Upload & Process:** User uploads an ePub -> Backend saves it -> Background thread starts extracting text and generating audio chunks via Edge TTS -> Audio files are saved locally.
2. **Playback:** User clicks play -> Frontend streams the audio chunk from the backend -> Media Session API hooks into OS controls -> Audio continues playing when the screen is locked or connected to a car.
3. **Sync:** Every few seconds, the frontend sends the current playback position to the backend, which updates the SQLite database. Upon reloading or switching devices, playback resumes from this timestamp.

## 5. Deployment

- **Dockerized (Single Container):** The application runtime (frontend assets and Python server) is packaged into a single `Dockerfile`.
- **Volumes:** A single mapped volume (e.g., `/app/data`) stores the SQLite database and media files, ensuring data persists across container restarts.
- **Reverse Proxy:** Expected to be placed behind a simple reverse proxy (like Caddy or Nginx) for automatic HTTPS, which is required for PWAs and the Media Session API.
- **Hugging Face Spaces:** The same Dockerfile can be deployed as a Docker Space via `scripts/deploy_hf.py`. The script handles Space creation, environment variable configuration, and uploads with the required HF metadata. Persistent storage is needed to retain data across Space sleeps and restarts.

