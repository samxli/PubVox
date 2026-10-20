# PubVox 🎧📖

> Your personal, self-hosted ePub to Audiobook streaming server.

**PubVox** is an ultra-lightweight web application that converts your ePub files into streamable audiobooks. Designed for simplicity and optimized for commuting, it features seamless background playback, cross-device progress tracking, and an incredibly small server footprint.

## ✨ Features

- **📚 ePub to Audio:** Upload an ePub and PubVox parses its chapters, then generates MP3 audio in the background using [Edge TTS][edge-tts].
- **🚗 Commute-Ready (PWA):** Built as a Progressive Web App utilizing the Media Session API. Lock your screen, connect to your car's Bluetooth, and use native media controls to play, pause, and skip—just like Spotify or Audible.
- **🔖 Progress Sync:** Pick up exactly where you left off. PubVox syncs your listening progress across all your devices.
- **🏠 Single Shared Library:** Designed for one local user per instance, with no accounts or authentication in the current slice.
- **⚡ Ultra-Lightweight:** Runs in a single Docker container with an SQLite database. Perfect for a 1GB VPS, a Raspberry Pi, or your local desktop.

## 🏗️ Architecture & Tech Stack

- **Backend:** Python (FastAPI)
- **Frontend:** Vanilla JavaScript / HTML5 / CSS (Minimal PWA, served directly by the backend)
- **Database:** SQLite (No external DB containers required!)
- **TTS Engine:** `edge-tts` (Background worker, one chapter at a time)
- **Deployment:** Single-container Docker (recommended), optional Hugging Face Space

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## 🚀 Quick Start (Docker)

The repository includes a `docker-compose.yml` with TTS enabled and a persistent volume.

1. Clone this repository and enter it:

   ```shell
   git clone https://github.com/samxli/PubVox.git
   cd PubVox
   ```

2. Build and start the container:

   ```shell
   docker compose up -d
   ```

3. Open your browser and navigate to `http://localhost:8000`.

4. Upload an ePub. Chapters are queued immediately; audio becomes playable as each chapter finishes generating.

The compose file enables TTS by default. Set `PUBVOX_TTS_ENABLED=0` to disable it. If you previously stored data in a local `./data` bind mount, copy that directory into the `pubvox-data` volume before switching.

To run without Compose:

```shell
docker build -t pubvox .
docker run -d --name pubvox -p 8000:7860 -e PUBVOX_TTS_ENABLED=1 -v pubvox-data:/app/data pubvox
```

The container listens on port `7860`; Compose maps it to `8000`. Override the container port with the `PORT` environment variable if needed.

For the PWA and Media Session API to work properly on mobile devices, PubVox must be served over HTTPS once you leave `localhost`. We recommend running it behind a reverse proxy like Caddy, Nginx Proxy Manager, or Traefik.

## ⚙️ Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PUBVOX_DATA_DIR` | `./data` (`/app/data` in Docker) | Directory for `app.db`, uploaded ePubs, and generated audio |
| `PUBVOX_TTS_ENABLED` | off | Set to `1`, `true`, `yes`, or `on` to generate audio with Edge TTS |
| `PUBVOX_TTS_VOICE` | `en-US-AriaNeural` | Edge TTS voice name |
| `PORT` | `7860` (Docker image) | Container port used by the Docker entrypoint |

With TTS disabled, uploads are still parsed and stored, but no audio is generated and books are marked unavailable.

## ☁️ Deployment Options

### Docker (recommended)

Any VPS, home server, NAS, or desktop that runs Docker can host PubVox for free. Use the Compose setup above and put it behind an HTTPS reverse proxy for mobile playback. PubVox has no authentication, so keep it on your LAN or VPN, or add auth at the reverse proxy before exposing it to the internet.

### Hugging Face Spaces (optional, paid)

PubVox can still run as a Docker Space, and [`scripts/deploy_hf.py`](scripts/deploy_hf.py) automates Space creation, storage, and uploads. This is no longer a free option: Docker Spaces require a paid Hugging Face plan, and persistent storage buckets are billed per TB. CPU Basic hardware itself has no hourly charge, but you cannot create a Docker Space without a paid plan.

If you want to use it anyway, see **[HF_DEPLOY.md](HF_DEPLOY.md)** for prerequisites, costs, deployment steps, and troubleshooting.

## 🛠️ Development Setup

If you want to run PubVox locally without Docker or contribute to the project:

1. Clone the repository:

   ```shell
   git clone https://github.com/samxli/PubVox.git
   cd PubVox
   ```

2. Install dependencies:

   ```shell
   pip install -r requirements.txt
   ```

3. Run the development server:

   ```shell
   python main.py
   ```

   The app is served at `http://localhost:8000`.

   By default, uploaded books are parsed and stored without contacting the TTS provider. To enable Edge TTS generation during development:

   ```shell
   PUBVOX_TTS_ENABLED=1 python main.py
   ```

   Local data (SQLite database, uploads, audio) is written to `./data` unless `PUBVOX_DATA_DIR` is set.

## 🧪 Testing

```shell
pip install -r requirements-dev.txt
python -m pytest
```

Tests use `pytest` with FastAPI's `TestClient` and a temporary data directory.

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and data flow
- [HF_DEPLOY.md](HF_DEPLOY.md) — optional Hugging Face Spaces deployment
- [SECURITY.md](SECURITY.md) — security policy and deployment guidance

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

[edge-tts]: https://github.com/rany2/edge-tts
