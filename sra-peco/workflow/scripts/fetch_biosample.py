"""Fetch BioSample records from NCBI and store normalized per-sample JSON."""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _strip_namespaces(xml_bytes):
    return re.sub(rb'\sxmlns(:\w+)?="[^"]*"', b"", xml_bytes)


def _parse(xml_bytes):
    root = ET.fromstring(_strip_namespaces(xml_bytes))
    records = {}
    for biosample in root.findall(".//BioSample"):
        accession = biosample.get("accession")
        if not accession:
            continue
        organism = biosample.findtext(".//Organism/OrganismName")
        attributes = {}
        for attribute in biosample.findall(".//Attribute"):
            name = (
                attribute.get("harmonized_name")
                or attribute.get("attribute_name")
                or attribute.get("display_name")
            )
            if name:
                attributes[name] = (attribute.text or "").strip()
        records[accession] = {
            "accession": accession,
            "organism": (organism or "").strip(),
            "attributes": attributes,
        }
    return records


def _fetch_batch(ids, email, api_key, max_retries):
    params = {
        "db": "biosample",
        "id": ",".join(ids),
        "retmode": "xml",
        "tool": "sra-peco",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    delay = 1.0
    for attempt in range(max_retries):
        try:
            response = requests.post(EFETCH_URL, data=params, timeout=120)
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
    raise RuntimeError("BioSample fetch exhausted retries")


def main():
    samns = list(snakemake.params.samns)
    outputs = list(snakemake.output)
    if len(samns) != len(outputs):
        raise RuntimeError("SAMN list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    batch_size = int(snakemake.params.batch_size)
    max_retries = int(snakemake.params.max_retries)

    records = {}
    for start in range(0, len(samns), batch_size):
        batch = samns[start : start + batch_size]
        records.update(_parse(_fetch_batch(batch, email, api_key, max_retries)))

    missing = [samn for samn in samns if samn not in records]
    if missing:
        raise RuntimeError(
            "NCBI returned no BioSample record for: " + ", ".join(sorted(missing))
        )

    for samn, path in zip(samns, outputs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(records[samn], handle, indent=2, sort_keys=True)
            handle.write("\n")


if __name__ == "__main__":
    main()
