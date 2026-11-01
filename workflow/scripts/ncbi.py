"""Shared NCBI E-utilities helpers."""

import re
import time

import requests

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def strip_namespaces(xml_bytes):
    """Remove XML namespace declarations from an efetch response."""
    return re.sub(rb'\sxmlns(:\w+)?="[^"]*"', b"", xml_bytes)


def fetch_efetch(
    db,
    ids,
    email,
    api_key,
    max_retries,
    timeout=120,
    error_label="efetch",
    tool="sra-peco",
):
    """POST an efetch request and return the raw response body."""
    params = {
        "db": db,
        "id": ",".join(ids),
        "retmode": "xml",
        "tool": tool,
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key

    delay = 1.0
    for attempt in range(max_retries):
        try:
            response = requests.post(EFETCH_URL, data=params, timeout=timeout)
            if response.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{error_label} exhausted retries")
