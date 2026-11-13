"""Shared NCBI E-utilities helpers."""

import json
import re
import time
import xml.etree.ElementTree as ET

import requests

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def strip_namespaces(xml_bytes):
    """Flatten XML namespaces so ElementTree can match plain tag names.

    Removing the declarations alone is not enough: GEO-brokered SRA records
    carry ``xsi:noNamespaceSchemaLocation`` attributes, and ENA-derived ones
    occasionally use prefixed elements. A prefix left without its declaration
    makes ElementTree raise ``unbound prefix``, which used to kill the whole
    fetch job (window 6, ERR10479009 batch). Strip the prefixes too.
    """
    text = re.sub(rb'\sxmlns(:\w+)?="[^"]*"', b"", xml_bytes)
    text = re.sub(rb"<(/?)[A-Za-z_][\w.-]*:", rb"<\1", text)  # <ns:tag>
    text = re.sub(
        rb"(\s)[A-Za-z_][\w.-]*:(?=[A-Za-z_][\w.-]*=)", rb"\1", text
    )  # ns:attribute=
    return text


def parse_efetch(xml_bytes, parse_fn, record_tag=None):
    """Parse an efetch response, degrading to per-record parsing.

    Returns ``(records, failures)``. A whole response that will not parse is
    retried one record at a time: one malformed record must not fail the fetch
    job, because the caller turns missing accessions into ENA fallbacks or
    stubs. ``failures`` counts records that could not be parsed at all.
    """
    soft = strip_namespaces(xml_bytes)
    try:
        return parse_fn(soft), 0
    except ET.ParseError:
        if not record_tag:
            return {}, 1

    tag = record_tag.encode()
    pattern = re.compile(rb"<" + tag + rb"(?:\s[^>]*)?>.*?</" + tag + rb">", re.S)
    records = {}
    failures = 0
    for chunk in pattern.findall(soft):
        try:
            records.update(parse_fn(b"<ROOT>" + chunk + b"</ROOT>"))
        except ET.ParseError:
            failures += 1
    return records, failures


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
