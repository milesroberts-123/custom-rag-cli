"""HTTP GET helper with retry/backoff for metadata APIs."""

import time

import requests


def get(url, params=None, max_retries=5, timeout=120):
    """GET a URL, retrying 429s and returning None for 404."""
    delay = 1.0
    for attempt in range(max_retries):
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response
    raise RuntimeError(f"GET {url} exhausted retries")
