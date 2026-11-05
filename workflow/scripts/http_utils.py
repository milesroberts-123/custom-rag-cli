"""HTTP GET helper with retry/backoff for metadata APIs."""

import logging
import time

import requests

log = logging.getLogger(__name__)

# NCBI and Europe PMC intermittently return 5xx under load or when
# rate-limiting surfaces as a server error instead of a 429; retry these
# like 429s rather than failing a whole batch window on one flake.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get(url, params=None, max_retries=5, timeout=120):
    """GET a URL, retrying 429/5xx with backoff; returns None for 404.

    A ``Retry-After`` header, when present, wins over the exponential delay.
    Other 4xx responses raise immediately.
    """
    delay = 1.0
    for attempt in range(max_retries):
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code in RETRYABLE_STATUS:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.strip().isdigit():
                wait = float(retry_after)
            else:
                wait = delay
                delay *= 2
            log.warning(
                "GET %s -> %s (attempt %d/%d); retrying in %.1fs",
                url,
                response.status_code,
                attempt + 1,
                max_retries,
                wait,
            )
            time.sleep(wait)
            continue
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response
    raise RuntimeError(f"GET {url} exhausted retries")
