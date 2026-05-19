#!/usr/bin/env python3
"""Deploy PubVox to a Hugging Face Docker Space.

This script creates (or updates) a HF Space, configures environment variables,
and uploads the project files — injecting the required YAML frontmatter into
the README at upload time so the main repository stays clean for GitHub.

Usage:
    # Basic deploy (TTS disabled)
    python scripts/deploy_hf.py --repo-id username/pubvox

    # Deploy with Edge TTS enabled and a custom voice
    python scripts/deploy_hf.py --repo-id username/pubvox --tts-enabled --tts-voice en-US-AriaNeural

    # Dry run — show what would happen without uploading
    python scripts/deploy_hf.py --repo-id username/pubvox --dry-run

Prerequisites:
    - pip install huggingface_hub
    - A HF write token (export HF_TOKEN or pass --token)

By default, a storage bucket is mounted at /app/data for persistence.
Pass --no-storage to skip this step.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import textwrap
from pathlib import Path

try:
    from huggingface_hub import HfApi, SpaceHardware
except ImportError:
    raise SystemExit(
        "huggingface_hub is required. Install it with:\n"
        "  pip install huggingface_hub"
    )

try:
    from huggingface_hub import Volume
except ImportError:
    raise SystemExit(
        "Your huggingface_hub version is too old (Volume class not found).\n"
        "  pip install --upgrade huggingface_hub"
    )


ROOT_DIR = Path(__file__).resolve().parent.parent
README_PATH = ROOT_DIR / "README.md"

HF_README_FRONTMATTER = textwrap.dedent("""\
    ---
    title: PubVox
    sdk: docker
    app_port: 7860
    ---
""")

DEFAULT_VARIABLES: dict[str, str] = {
    "PUBVOX_DATA_DIR": "/app/data",
}

# Files/dirs to exclude from the HF upload
IGNORE_PATTERNS = [
    ".git",
    ".github",
    ".venv",
    ".venv/**",
    "__pycache__",
    "__pycache__/**",
    "*.pyc",
    ".DS_Store",
    "scripts",
    "scripts/**",
    "data",
    "data/**",
    "*.db",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy PubVox to a Hugging Face Docker Space.",
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="HF Space repo ID (e.g. 'username/pubvox').",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="HF write token. Falls back to HF_TOKEN env var or cached login.",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        default=False,
        help="Create the Space as private (default: public).",
    )
    parser.add_argument(
        "--hardware",
        default="cpu-basic",
        choices=[h.value for h in SpaceHardware],
        help="Space hardware tier (default: cpu-basic).",
    )
    parser.add_argument(
        "--no-storage",
        action="store_true",
        default=False,
        help="Skip persistent storage setup.",
    )
    parser.add_argument(
        "--tts-enabled",
        action="store_true",
        default=False,
        help="Set PUBVOX_TTS_ENABLED=1 in the Space.",
    )
    parser.add_argument(
        "--tts-voice",
        default="en-US-AriaNeural",
        help="Edge TTS voice name (default: en-US-AriaNeural).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without uploading.",
    )
    return parser.parse_args()


def build_variables(tts_enabled: bool, tts_voice: str) -> dict[str, str]:
    """Merge default and optional variables into a single dict."""
    variables = dict(DEFAULT_VARIABLES)
    if tts_enabled:
        variables["PUBVOX_TTS_ENABLED"] = "1"
        if tts_voice:
            variables["PUBVOX_TTS_VOICE"] = tts_voice
    return variables


def build_readme_content() -> str:
    """Return the README with HF frontmatter prepended."""
    original = README_PATH.read_text(encoding="utf-8")
    # Strip any existing frontmatter just in case
    if original.startswith("---"):
        _, _, body = original.partition("\n---\n")
        if not body:
            # Malformed or no closing ---, use as-is
            body = original
        original = body.lstrip("\n")
    return HF_README_FRONTMATTER + original


def check_auth(api: HfApi) -> None:
    """Verify the token is valid before attempting any operations."""
    try:
        api.whoami()
    except Exception as exc:
        msg = (
            "Authentication failed. Please provide a valid HF write token via:\n"
            "  --token <token>  or  HF_TOKEN env var  or  `huggingface-cli login`\n"
            f"\nOriginal error: {exc}"
        )
        raise SystemExit(msg) from exc


def main() -> None:
    args = parse_args()
    api = HfApi(token=args.token)

    check_auth(api)

    variables = build_variables(args.tts_enabled, args.tts_voice)

    print(f"Repository:  {args.repo_id}")
    print(f"Hardware:    {args.hardware}")
    print(f"Storage:     {("skipped" if args.no_storage else "/app/data (bucket)")}")
    print(f"Private:     {args.private}")
    print(f"Variables:   {variables}")
    print()

    if args.dry_run:
        print("[dry-run] Would create/update the Space and upload files.")
        print(f"[dry-run] README would have {len(HF_README_FRONTMATTER.splitlines())} lines of frontmatter prepended.")
        print(f"[dry-run] Upload dir (copy of project with patched README): <tempdir>")
        print(f"[dry-run] Ignore patterns: {IGNORE_PATTERNS}")
        return

    # Create the Space (no-op if it already exists)
    print("Creating Space (if it doesn't exist)...")
    api.create_repo(
        repo_id=args.repo_id,
        repo_type="space",
        space_sdk="docker",
        private=args.private,
        exist_ok=True,
    )
    # Always enforce the visibility setting (create_repo is a no-op when the
    # Space already exists, so --private would otherwise be silently ignored).
    api.update_repo_settings(
        repo_id=args.repo_id,
        repo_type="space",
        private=args.private,
    )

    # Set persistent storage (create a bucket and mount it at /app/data)
    if not args.no_storage:
        namespace = args.repo_id.split("/")[0]
        space_name = args.repo_id.split("/")[1]
        bucket_id = f"{namespace}/{space_name}-data"
        print(f"Creating storage bucket '{bucket_id}'...")
        api.create_bucket(bucket_id=bucket_id, exist_ok=True)
        print(f"Mounting bucket at /app/data...")
        api.set_space_volumes(
            repo_id=args.repo_id,
            volumes=[
                Volume(
                    type="bucket",
                    source=f"{namespace}/{space_name}-data",
                    mount_path="/app/data",
                ),
            ],
        )

    # Set hardware
    print(f"Setting hardware to {args.hardware}...")
    api.request_space_hardware(
        repo_id=args.repo_id,
        hardware=args.hardware,
    )

    # Set environment variables
    print("Setting environment variables...")
    for key, value in variables.items():
        api.add_space_variable(
            repo_id=args.repo_id,
            key=key,
            value=value,
        )

    # Upload files with frontmatter-injected README (single commit)
    print("Uploading files...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        shutil.copytree(
            ROOT_DIR,
            tmp_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
            symlinks=False,
        )
        tmp_readme = Path(tmp_dir) / "README.md"
        tmp_readme.write_text(build_readme_content(), encoding="utf-8")

        api.upload_folder(
            repo_id=args.repo_id,
            repo_type="space",
            folder_path=str(tmp_dir),
            commit_message="Deploy PubVox to Hugging Face Space",
        )

    print()
    print(f"Done! Your Space is at: https://huggingface.co/spaces/{args.repo_id}")
    print()
    print("Post-deploy checklist:")
    print("  1. Verify /api/health returns {\"status\":\"ok\"}")
    print("  2. Upload a small .epub file")
    print("  3. If TTS is enabled, wait for chapter audio generation")
    print("  4. Restart the Space and confirm data persists")


if __name__ == "__main__":
    main()
