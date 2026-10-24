# Deploying PubVox to Hugging Face Spaces

[← Back to the main README](README.md)

Hugging Face Spaces is an **optional, secondary deployment target** for PubVox. It is no longer a free hosting path: as of October 2026, Docker Spaces require a paid Hugging Face plan. Self-hosting with Docker (see the [Quick Start](README.md#-quick-start-docker)) remains the recommended and free option.

## Cost caveats

Hugging Face changed Spaces pricing in 2026. Current constraints, per the [Spaces documentation](https://huggingface.co/docs/hub/spaces-overview) and [pricing page](https://huggingface.co/pricing):

- **Docker and Gradio Spaces require a paid plan to create** — PRO for personal accounts, Team or Enterprise for organizations. Static HTML Spaces remain free, but PubVox is a Docker app.
- **CPU Basic hardware has no hourly charge**, but it is only available once the Space exists under a paid plan.
- **Storage Buckets are billed per TB beyond any allowance included with your plan.** PubVox needs a bucket mounted at `/app/data` to keep the library, uploads, and generated audio across restarts.
- Free personal accounts can still run up to two Gradio Spaces on ZeroGPU. That quota does not apply to Docker Spaces.

Check the Hugging Face pricing page before deploying; the numbers and plan requirements can change.

## What the deploy script does

[`scripts/deploy_hf.py`](scripts/deploy_hf.py) creates or updates a Docker Space and uploads a copy of the app. It:

1. Verifies your Hugging Face token.
2. Creates the Space (Docker SDK) and enforces the requested visibility.
3. Creates a private Storage Bucket named `<namespace>/<space-name>-data` and mounts it at `/app/data`.
4. Requests the selected hardware tier (default `cpu-basic`).
5. Sets the Space variables (`PUBVOX_DATA_DIR`, `PUBVOX_COOKIE_SECURE`, `PUBVOX_TTS_ENABLED`, `PUBVOX_TTS_VOICE`).
6. Uploads `main.py`, `pubvox/`, `requirements.txt`, `Dockerfile`, and the docs, with YAML frontmatter prepended to the README so the GitHub copy stays clean.

## Prerequisites

- A [Hugging Face](https://huggingface.co) account with a plan that can create Docker Spaces
- A write access token from [hf.co/settings/tokens](https://huggingface.co/settings/tokens)
- Python with a recent `huggingface_hub`: `pip install --upgrade "huggingface_hub>=1.15.0,<2.0.0"` (`Volume` support is required)

## Deploy

Set the token in your environment so it does not land in shell history:

```shell
export HF_TOKEN=<your-hf-token>
python scripts/deploy_hf.py --repo-id <your-username>/pubvox --private --tts-enabled
```

New Spaces are public by default. Pass `--private` for a personal library. Also set a `PUBVOX_PASSWORD` Space secret (see [Security notes](#security-notes)) — without it a public Space exposes your uploaded books and generated audio to anyone who can reach the URL. Rerunning the script without `--private` leaves an existing Space's visibility unchanged, so an already-private Space stays private.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--private` | Create the Space private; also makes an existing Space private (omitted: existing visibility is kept) |
| `--tts-enabled` | Set `PUBVOX_TTS_ENABLED=1` |
| `--tts-voice` | Edge TTS voice (default `en-US-AriaNeural`) |
| `--hardware` | Space hardware tier (default `cpu-basic`) |
| `--no-storage` | Skip bucket creation and mounting; does not unmount an existing bucket, so data may still persist |
| `--dry-run` | Print the plan without creating or uploading anything |

Run `python scripts/deploy_hf.py --help` for the full list.

## Persistent storage

The script creates a private storage bucket and mounts it at `/app/data`, which is where PubVox keeps `app.db`, uploaded ePubs, and generated chapter audio. No manual setup is needed unless you pass `--no-storage`. `--no-storage` only skips this setup step; it does not unmount a bucket already attached to the Space, so an existing Space can keep persisting data.

If the bucket already exists and is public, the script stops with an error. Make it private in Hugging Face settings or delete it, then rerun. Existing mounts other than `/app/data` are preserved; if `/app/data` is already mounted to a different bucket, the script stops and asks you to unmount or migrate it first.

## Configuration on the Space

| Variable | Value set by the script |
| --- | --- |
| `PUBVOX_DATA_DIR` | `/app/data` |
| `PUBVOX_COOKIE_SECURE` | `1` (Spaces serve HTTPS) |
| `PUBVOX_TTS_ENABLED` | `1` with `--tts-enabled`, otherwise `0` |
| `PUBVOX_TTS_VOICE` | `--tts-voice` value, only when TTS is enabled |

## Smoke test

1. Open `/api/health` and verify it returns `{"status":"ok"}`.
2. Upload a small `.epub` file.
3. If TTS is enabled, wait for generated chapter audio.
4. Restart the Space (or let it sleep), then confirm the library, progress, uploaded ePub, and generated audio still exist.

## Troubleshooting

- **`402` / payment required when creating the Space** — Docker Spaces need a paid plan. Upgrade the account, or self-host with Docker instead.
- **`Volume` import error** — upgrade `huggingface_hub` to `>=1.15.0`.
- **Library disappears after a restart** — the Space has no bucket mounted at `/app/data` (for example, it was first deployed with `--no-storage`). Rerun without `--no-storage` to create and mount one.
- **Audio generation is slow or stuck at `processing`** — Edge TTS runs sequentially, one chapter at a time, and long books can take a while. Check the Space logs; failed chapters can be retried from the UI.

## Security notes

See [SECURITY.md](SECURITY.md) for the general policy. For Spaces specifically:

- PubVox serves a single shared library. Set a `PUBVOX_PASSWORD` Space secret to require a password, and keep the Space private unless you intend to publish your library.
- Keep the storage bucket private; it contains the SQLite database and your ePub files.
- Store any future credentials as Space secrets, not as committed files or public variables.
