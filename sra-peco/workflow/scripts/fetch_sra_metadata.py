"""Fetch SRA run metadata and store compact per-run JSON records."""

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


def _text(element, path):
    node = element.find(path)
    return (node.text or "").strip() if node is not None and node.text else ""


def _parse(xml_bytes):
    root = ET.fromstring(_strip_namespaces(xml_bytes))
    records = {}
    for package in root.findall(".//EXPERIMENT_PACKAGE"):
        experiment = package.find(".//EXPERIMENT")
        if experiment is None:
            continue

        library = experiment.find(".//LIBRARY_DESCRIPTOR")
        sample = package.find(".//SAMPLE")
        study = package.find(".//STUDY")

        sample_name = sample.get("alias", "") if sample is not None else ""
        if sample is not None:
            for submitter_id in sample.findall(".//SUBMITTER_ID"):
                if submitter_id.get("label") == "Sample name" and submitter_id.text:
                    sample_name = submitter_id.text.strip()

        attributes = {}
        for attribute in package.findall(".//SAMPLE_ATTRIBUTE"):
            tag = _text(attribute, "TAG")
            value = _text(attribute, "VALUE")
            if tag:
                attributes[tag] = value

        record = {
            "experiment_accession": experiment.get("accession"),
            "experiment_title": _text(experiment, "TITLE"),
            "library_name": (
                _text(library, "LIBRARY_NAME") if library is not None else ""
            ),
            "library_strategy": (
                _text(library, "LIBRARY_STRATEGY") if library is not None else ""
            ),
            "sample_accession": sample.get("accession") if sample is not None else None,
            "sample_name": sample_name,
            "study_accession": study.get("accession") if study is not None else None,
            "study_title": _text(package, ".//STUDY_TITLE"),
            "study_abstract": _text(package, ".//STUDY_ABSTRACT"),
            "sample_attributes": attributes,
        }
        for run in package.findall(".//RUN"):
            accession = run.get("accession")
            if accession:
                records[accession] = {**record, "run": accession}
    return records


def _fetch_batch(ids, email, api_key, max_retries):
    params = {
        "db": "sra",
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
            response = requests.post(EFETCH_URL, data=params, timeout=180)
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
    raise RuntimeError("SRA metadata fetch exhausted retries")


def main():
    runs = list(snakemake.params.runs)
    outputs = list(snakemake.output)
    if len(runs) != len(outputs):
        raise RuntimeError("run list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    batch_size = int(snakemake.params.batch_size)
    max_retries = int(snakemake.params.max_retries)

    records = {}
    for start in range(0, len(runs), batch_size):
        batch = runs[start : start + batch_size]
        records.update(_parse(_fetch_batch(batch, email, api_key, max_retries)))

    missing = [run for run in runs if run not in records]
    if missing:
        raise RuntimeError("NCBI returned no SRA record for: " + ", ".join(sorted(missing)))

    for run, path in zip(runs, outputs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(records[run], handle, indent=2, sort_keys=True)
            handle.write("\n")


if __name__ == "__main__":
    main()
