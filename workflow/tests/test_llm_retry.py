"""Tests for the chat client retry behavior in llm.py."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import APITimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import llm


class FakeCompletions:
    def __init__(self, failures, content):
        self.failures = failures
        self.calls = 0
        self.content = content

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise APITimeoutError(request=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, failures=2, content=None):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(failures, content or json.dumps({"ok": True}))
        )


def test_chat_json_retries_transient_timeouts(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    client = FakeClient(failures=2)
    result = llm.chat_json(client, "qwen3.8", [{"role": "user", "content": "hi"}])
    assert result == {"ok": True}
    assert client.chat.completions.calls == 3


def test_chat_json_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    client = FakeClient(failures=5)
    with pytest.raises(APITimeoutError):
        llm.chat_json(client, "qwen3.8", [{"role": "user", "content": "hi"}])
    assert client.chat.completions.calls == 3


def test_chat_json_retry_count_is_configurable(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    client = FakeClient(failures=0)
    result = llm.chat_json(
        client, "qwen3.8", [{"role": "user", "content": "hi"}], retries=1
    )
    assert result == {"ok": True}
    assert client.chat.completions.calls == 1
