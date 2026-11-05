"""Client helpers for Ollama's chat and decision endpoints.

Chat requests use Ollama's native /api/chat endpoint rather than the
OpenAI-compatible /v1 surface. Two reasons:

- ``think: false`` is a top-level field of the native API and reliably
  disables reasoning traces on thinking-capable models; the OpenAI-compatible
  endpoint ignores it. Labels are short JSON answers, and reasoning
  chains-of-thought are pure latency.
- Native ``options`` gives per-request ``num_predict``/``num_ctx`` control.

The decision endpoint (/v1/systemone) is unchanged.
"""

import json
import os
import re
import time

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _server(server_url):
    return (os.environ.get("OLLAMA_SERVER") or server_url).rstrip("/")


def _key(api_key):
    return os.environ.get("OLLAMA_API_KEY") or api_key


def systemone(
    server_url, api_key, model, state, questions, keep_alive="30m", timeout=120
):
    """Ask Ollama's decision endpoint (/v1/systemone) one or more questions.

    A 404 here almost always means the decision model is missing on the server
    (Ollama returns ``{"error": "model 'tev1:4b' not found"}``). That failure
    used to be silent because every caller falls back to the chat model, so an
    entire window could run with the decision layer dead. Raise a loud,
    actionable error instead; callers still catch it and fall back, but the
    job log now says exactly what to fix.
    """
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
    if response.status_code == 404:
        try:
            detail = response.json().get("error", "")
        except ValueError:
            detail = response.text[:200]
        raise RuntimeError(
            f"decision model {model!r} is unavailable at "
            f"{_server(server_url)}/v1/systemone (HTTP 404: {detail}). "
            f"Pull it on the model-server node (`ollama pull {model}`) and "
            "verify with `ollama list`; labels fall back to the chat model "
            "until it is available."
        )
    response.raise_for_status()
    return response.json()


def _extract_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return fenced.group(1) if fenced else text


def chat_json(
    server_url,
    api_key,
    model,
    messages,
    model_params=None,
    max_tokens=1024,
    retries=3,
):
    """Send a chat request that must return a JSON object.

    JSON mode is forced and generation is capped at ``max_tokens``. Thinking
    is disabled by default; a step opts in with ``{"think": true}`` in its
    model params, which this function pulls out and sends as the top-level
    ``think`` field (it is not an Ollama runtime option). Everything else in
    ``model_params`` maps to runtime ``options`` (e.g. ``temperature``).
    Transient failures (connection loss, timeouts, HTTP 429/5xx from a busy
    shared server) are retried with backoff; JSON validation failures still
    propagate so callers can run their own correction loops.
    """
    params = dict(model_params or {})
    think = bool(params.pop("think", False))
    options = dict(params)
    options["num_predict"] = max_tokens
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "think": think,
        "options": options,
    }
    headers = {"Authorization": f"Bearer {_key(api_key)}"}
    url = f"{_server(server_url)}/api/chat"

    delay = 5.0
    for attempt in range(retries):
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=(30, 600)
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code in RETRYABLE_STATUS and attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        break

    body = response.json()
    if "error" in body:
        raise RuntimeError(f"Ollama error: {body['error']}")
    content = body.get("message", {}).get("content") or ""
    return json.loads(_extract_json(content))
