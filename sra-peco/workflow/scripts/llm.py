"""Client helpers for Ollama's chat and decision endpoints."""

import json
import os
import re

import requests
from openai import OpenAI


def _server(server_url):
    return (os.environ.get("OLLAMA_SERVER") or server_url).rstrip("/")


def _key(api_key):
    return os.environ.get("OLLAMA_API_KEY") or api_key


def make_client(server_url, api_key):
    """Build an OpenAI-compatible client for the Ollama server."""
    return OpenAI(base_url=f"{_server(server_url)}/v1", api_key=_key(api_key))


def systemone(server_url, api_key, model, state, questions, keep_alive="30m", timeout=120):
    """Ask Ollama's decision endpoint (/v1/systemone) one or more questions."""
    payload = {
        "model": model,
        "state": state,
        "questions": questions,
        "keep_alive": keep_alive,
    }
    response = requests.post(
        f"{_server(server_url)}/v1/systemone",
        json=payload,
        headers={"Authorization": f"Bearer {_key(api_key)}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _extract_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return fenced.group(1) if fenced else text


def chat_json(client, model, messages, model_params=None, max_tokens=4096):
    """Send a chat request that must return a JSON object."""
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    kwargs.update(model_params or {})
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    return json.loads(_extract_json(content))
