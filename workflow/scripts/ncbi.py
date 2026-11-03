"""Shared NCBI E-utilities helpers."""

import json
import re
import time

import requests

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


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


def _get_json(url, params, timeout, error_label, max_retries):
    """GET a JSON response with retry on transient failures."""
    delay = 1.0
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError):
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{error_label} exhausted retries")


def esearch_ids(db, term, email, api_key, max_retries, timeout=120):
    """Return the ID list for an ESearch query."""
    params = {
        "db": db,
        "term": term,
        "retmode": "json",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    payload = _get_json(ESEARCH_URL, params, timeout, f"esearch {db}", max_retries)
    return payload.get("esearchresult", {}).get("idlist", [])


def esummary(db, ids, email, api_key, max_retries, timeout=120):
    """Return the document summaries for one or more ESummary UIDs."""
    params = {
        "db": db,
        "id": ",".join(ids),
        "retmode": "json",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    payload = _get_json(ESUMMARY_URL, params, timeout, f"esummary {db}", max_retries)
    return payload.get("result", {})
