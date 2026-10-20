"""Tests for the Space volume retention logic in the deploy script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from huggingface_hub import Volume

spec = importlib.util.spec_from_file_location(
    "deploy_hf", Path(__file__).resolve().parent.parent / "scripts" / "deploy_hf.py"
)
deploy_hf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_hf)

BUCKET = "user/pubvox-data"


def test_unrelated_mounts_are_preserved() -> None:
    existing = [Volume(type="model", source="user/model", mount_path="/models")]
    volumes = deploy_hf.retained_volumes(existing, BUCKET)
    assert [v.mount_path for v in volumes] == ["/models", "/app/data"]
    assert volumes[1].source == BUCKET


def test_redeploy_replaces_own_bucket_mount() -> None:
    existing = [Volume(type="bucket", source=BUCKET, mount_path="/app/data")]
    volumes = deploy_hf.retained_volumes(existing, BUCKET)
    assert len(volumes) == 1
    assert volumes[0].source == BUCKET


def test_foreign_data_bucket_mount_stops_deploy() -> None:
    existing = [Volume(type="bucket", source="user/other-data", mount_path="/app/data")]
    with pytest.raises(SystemExit, match="user/other-data"):
        deploy_hf.retained_volumes(existing, BUCKET)
