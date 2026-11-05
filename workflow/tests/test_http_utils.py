"""Retry/backoff behavior of the shared HTTP GET helper."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import http_utils  # noqa: E402


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")


def test_retries_5xx_then_succeeds(monkeypatch):
    responses = [FakeResponse(500), FakeResponse(503), FakeResponse(200)]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(http_utils.requests, "get", fake_get)
    monkeypatch.setattr(http_utils.time, "sleep", lambda s: None)

    response = http_utils.get("http://x", max_retries=5)
    assert response.status_code == 200
    assert len(calls) == 3


def test_exhausts_retries_and_raises(monkeypatch):
    monkeypatch.setattr(
        http_utils.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(500),
    )
    monkeypatch.setattr(http_utils.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="exhausted retries"):
        http_utils.get("http://x", max_retries=3)


def test_404_returns_none_without_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(
        http_utils.requests,
        "get",
        lambda url, params=None, timeout=None: calls.append(url) or FakeResponse(404),
    )
    assert http_utils.get("http://x") is None
    assert len(calls) == 1


def test_retry_after_header_wins_over_backoff(monkeypatch):
    sleeps = []
    responses = [FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200)]

    def fake_get(url, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(http_utils.requests, "get", fake_get)
    monkeypatch.setattr(http_utils.time, "sleep", sleeps.append)

    response = http_utils.get("http://x", max_retries=5)
    assert response.status_code == 200
    assert sleeps == [7.0]
