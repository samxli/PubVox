"""Password gate for the API: login mints a session cookie everything else requires."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def locked_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "PASSWORD", "sekrit")
    with TestClient(main.app) as client:
        yield client


def test_api_locked_without_session(locked_client: TestClient) -> None:
    assert locked_client.get("/api/books").status_code == 401


def test_shell_and_health_stay_open(locked_client: TestClient) -> None:
    assert locked_client.get("/api/health").status_code == 200
    assert locked_client.get("/").status_code == 200


def test_wrong_password_rejected(locked_client: TestClient) -> None:
    response = locked_client.post("/api/login", json={"password": "nope"})
    assert response.status_code == 401
    assert locked_client.get("/api/books").status_code == 401


def test_login_unlocks_api(locked_client: TestClient) -> None:
    response = locked_client.post("/api/login", json={"password": "sekrit"})
    assert response.status_code == 200
    assert locked_client.get("/api/books").status_code == 200
