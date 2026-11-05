"""Tests for the native /api/chat client in llm.py."""

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import llm


class _Response:
    def __init__(self, status_code=200, content=None):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._content is not None:
            return self._content
        return {"message": {"content": json.dumps({"ok": True})}}


def _messages():
    return [{"role": "user", "content": "hi"}]


def test_chat_json_payload_and_parse(monkeypatch):
    payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        payloads.append(json)
        return _Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    result = llm.chat_json(
        "http://node:11434",
        "ollama",
        "qwen3.8",
        _messages(),
        model_params={"temperature": 0},
    )
    assert result == {"ok": True}
    payload = payloads[0]
    assert payload["think"] is False
    assert payload["format"] == "json"
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] == 1024
    assert payload["options"]["temperature"] == 0
    assert payloads[0]["model"] == "qwen3.8"


def test_chat_json_custom_max_tokens(monkeypatch):
    payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        payloads.append(json)
        return _Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat_json("http://x", "k", "m", _messages(), max_tokens=2048)
    assert payloads[0]["options"]["num_predict"] == 2048


def test_chat_json_think_opt_in(monkeypatch):
    payloads = []

    def fake_post(url, json=None, headers=None, timeout=None):
        payloads.append(json)
        return _Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat_json(
        "http://x",
        "k",
        "m",
        _messages(),
        model_params={"temperature": 0, "think": True},
    )
    payload = payloads[0]
    assert payload["think"] is True
    assert "think" not in payload["options"]
    assert payload["options"]["temperature"] == 0


def test_chat_json_retries_transient_timeouts(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise requests.exceptions.Timeout()
        return _Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    result = llm.chat_json("http://x", "k", "m", _messages())
    assert result == {"ok": True}
    assert calls["n"] == 3


def test_chat_json_gives_up_after_retries(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    with pytest.raises(requests.exceptions.Timeout):
        llm.chat_json("http://x", "k", "m", _messages())
    assert calls["n"] == 3


def test_chat_json_retries_on_5xx(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _Response(status_code=503)
        return _Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    result = llm.chat_json("http://x", "k", "m", _messages())
    assert result == {"ok": True}
    assert calls["n"] == 3


def test_chat_json_fails_on_persistent_5xx(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **k: _Response(status_code=503)
    )
    with pytest.raises(requests.HTTPError):
        llm.chat_json("http://x", "k", "m", _messages())


def test_chat_json_retry_count_is_configurable(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    with pytest.raises(requests.exceptions.Timeout):
        llm.chat_json("http://x", "k", "m", _messages(), retries=1)
    assert calls["n"] == 1


def test_chat_json_raises_on_ollama_error_body(monkeypatch):
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *a, **k: _Response(content={"error": "model not found"}),
    )
    with pytest.raises(RuntimeError, match="model not found"):
        llm.chat_json("http://x", "k", "m", _messages())
