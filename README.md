# PubVox 🎧📖

> Your personal, self-hosted ePub to Audiobook streaming server.

**PubVox** is an ultra-lightweight web application that converts your ePub files into streamable audiobooks. Designed for simplicity and optimized for commuting, it features seamless background playback, cross-device progress tracking, and an incredibly small server footprint.

## ✨ Features

- **📚 ePub to Audio:** Automatically parses your ePubs and generates high-quality audio on the fly using [Edge TTS][edge-tts] (or small local models like Piper).
- **🚗 Commute-Ready (PWA):** Built as a Progressive Web App utilizing the Media Session API. Lock your screen, connect to your car's Bluetooth, and use native media controls to play, pause, and skip—just like Spotify or Audible.
- **🔖 Progress Sync:** Pick up exactly where you left off. PubVox syncs your listening progress across all your devices.
- **👥 Multi-User Support:** Individual accounts with isolated libraries and playback states.
- **⚡ Ultra-Lightweight:** Runs in a single Docker container with an SQLite database. Perfect for a 1GB VPS, a Raspberry Pi, or your local desktop.

## 🏗️ Architecture & Tech Stack

- **Backend:** Python (FastAPI/Flask)
- **Frontend:** Vanilla JavaScript / Alpine.js (Minimal PWA, served directly by the backend)
- **Database:** SQLite (No external DB containers required!)
- **TTS Engine:** `edge-tts` (Asynchronous processing)
- **Deployment:** Single-container Docker setup.

## 🚀 Quick Start (Docker)

The easiest way to get PubVox running is via Docker Compose.

1. Create a `docker-compose.yml` file:

   ```yaml
   version: '3.8'

   services:
     pubvox:
       image: pubvox/pubvox:latest
       container_name: pubvox
       restart: unless-stopped
       ports:
         - "8000:8000"
       volumes:
         - ./data:/app/data  # SQLite DB and generated audio
   ```

2. Run the container:

   ```shell
   docker-compose up -d
   ```

3. Open your browser and navigate to `http://localhost:8000`.

*(Note: For the PWA and Media Session API to work properly on mobile devices, PubVox must be served over HTTPS. We recommend putting it behind a reverse proxy like Caddy, Nginx Proxy Manager, or Traefik).*

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

## 🗺️ Roadmap

- Core ePub parsing and chapter segmentation
- Edge TTS integration and background queueing
- Minimal PWA UI and HTML5 Audio integration
- Media Session API hooks for lock-screen/car controls
- Multi-user SQLite auth
- Dockerization

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

[edge-tts]: https://github.com/rany2/edge-tts
