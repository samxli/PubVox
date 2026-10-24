"""Password gate for the API: login mints a session cookie everything else requires."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def reset_auth_state():
    main.session_tokens.clear()
    main.login_attempts.clear()
    yield
    main.session_tokens.clear()
    main.login_attempts.clear()


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


def test_unicode_password_compares_as_utf8(monkeypatch) -> None:
    monkeypatch.setattr(main, "PASSWORD", "pässphrase")
    with TestClient(main.app) as client:
        response = client.post("/api/login", json={"password": "pässphrase"})
        assert response.status_code == 200
        assert client.get("/api/books").status_code == 200


def test_expired_session_is_rejected(locked_client: TestClient) -> None:
    response = locked_client.post("/api/login", json={"password": "sekrit"})
    token = response.cookies[main.SESSION_COOKIE]
    main.session_tokens[token] = 0

    assert locked_client.get("/api/books").status_code == 401
    assert token not in main.session_tokens


def test_login_prunes_expired_sessions(locked_client: TestClient) -> None:
    main.session_tokens["expired"] = 0
    main.session_tokens["active"] = time.time() + 60

    response = locked_client.post("/api/login", json={"password": "sekrit"})

    assert response.status_code == 200
    assert "expired" not in main.session_tokens
    assert "active" in main.session_tokens


def test_login_rate_limited_after_failures(locked_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(main, "LOGIN_RATE_LIMIT", 2)

    assert locked_client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert locked_client.post("/api/login", json={"password": "nope"}).status_code == 401

    response = locked_client.post("/api/login", json={"password": "sekrit"})

    assert response.status_code == 429
    assert response.headers["Retry-After"].isdigit()


def test_secure_cookie_setting(locked_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(main, "COOKIE_SECURE", True)

    response = locked_client.post("/api/login", json={"password": "sekrit"})

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()
