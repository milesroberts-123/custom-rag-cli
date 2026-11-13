"""Fetch BioSample records and store normalized per-sample JSON.

NCBI db=biosample is the primary source (SAMN/SAMD/... accessions). ENA-origin
accessions (SAMEA...) are frequently absent from NCBI's mirror, so any
accession NCBI returns nothing for gets a fallback request to ENA's
BioSample XML API, which is parsed into the same normalized record shape.
Accessions missing from both sources still fail the job loudly.
"""

import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from ncbi import fetch_efetch, parse_efetch, strip_namespaces

ENA_XML_URL = "https://www.ebi.ac.uk/ena/browser/api/xml/{accession}"
ENA_RATE_LIMIT_SECONDS = 0.3


def _parse(xml_bytes):
    root = ET.fromstring(strip_namespaces(xml_bytes))
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
            "fetch_source": "ncbi",
        }
    return records


def parse_ena_sample(xml_bytes):
    """Parse an INSDC BioSample XML from ENA into the normalized record shape.

    ENA duplicates some tags (e.g. ``organism`` appears as both a structured
    attribute and a plain one); last value wins, matching NCBI behavior where
    a later attribute overwrites an earlier one in the attributes dict.
    """
    root = ET.fromstring(xml_bytes)
    sample = root.find(".//SAMPLE")
    if sample is None:
        return None
    accession = sample.get("accession")
    attributes = {}
    for attribute in sample.findall(".//SAMPLE_ATTRIBUTE"):
        tag = attribute.findtext("TAG")
        value = attribute.findtext("VALUE")
        if tag and value:
            attributes[tag.strip()] = value.strip()
    organism = sample.findtext(".//SAMPLE_NAME/SCIENTIFIC_NAME") or ""
    return {
        "accession": accession,
        "organism": (attributes.get("organism") or organism).strip(),
        "attributes": attributes,
        "fetch_source": "ena",
    }


def _ena_record(accession):
    """Fetch one BioSample record from ENA, retrying transient failures."""
    time.sleep(ENA_RATE_LIMIT_SECONDS)
    delay = 1.0
    for attempt in range(3):
        try:
            response = requests.get(
                ENA_XML_URL.format(accession=accession), timeout=120
            )
            if response.status_code in (429, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            response.raise_for_status()
            return parse_ena_sample(response.content)
        except requests.RequestException:
            if attempt == 2:
                return None
            time.sleep(delay)
            delay *= 2
    return None


from script_logging import setup as _setup

LOGGER = _setup("fetch_biosample")


def main():
    samns = list(snakemake.params.samns)
    outputs = list(snakemake.output)
    if len(samns) != len(outputs):
        raise RuntimeError("SAMN list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    batch_size = int(snakemake.params.batch_size)
    max_retries = int(snakemake.params.max_retries)

    # Existing outputs are kept: with window batching, later windows re-declare
    # samples fetched by earlier windows, and those fetches must be no-ops.
    todo = [
        (samn, path) for samn, path in zip(samns, outputs) if not Path(path).exists()
    ]
    LOGGER.info(
        "BioSample fetch: %d accessions (%d already cached)",
        len(samns),
        len(samns) - len(todo),
    )

    records = {}
    batches = [todo[i : i + batch_size] for i in range(0, len(todo), batch_size)]
    for index, batch in enumerate(batches, start=1):
        LOGGER.info(
            "NCBI efetch db=biosample batch %d/%d (%d accessions)",
            index,
            len(batches),
            len(batch),
        )
        parsed, failures = parse_efetch(
            fetch_efetch(
                "biosample",
                [samn for samn, _ in batch],
                email,
                api_key,
                max_retries,
                timeout=120,
                error_label="BioSample fetch",
            ),
            _parse,
            "BioSample",
        )
        records.update(parsed)
        if failures:
            LOGGER.warning(
                "batch %d: %d record(s) did not parse; ENA fallback covers them",
                index,
                failures,
            )
        LOGGER.info(
            "batch %d/%d parsed (%d records total)",
            index,
            len(batches),
            len(records),
        )

    # ENA-origin accessions are usually absent from NCBI's BioSample mirror;
    # fall back to ENA's XML API for anything NCBI does not have.
    missing = [samn for samn, _ in todo if samn not in records]
    if missing:
        LOGGER.warning(
            "%d accessions missing from NCBI; falling back to ENA", len(missing)
        )
    for samn in missing:
        record = _ena_record(samn)
        if record is not None:
            LOGGER.info("fetched %s from ENA", samn)
            records[samn] = record
        else:
            LOGGER.warning("ENA returned no record for %s", samn)

    unresolved = sorted(samn for samn, _ in todo if samn not in records)
    if unresolved:
        LOGGER.error("no BioSample record for %d accessions", len(unresolved))
        raise RuntimeError(
            "No BioSample record found in NCBI or ENA for: " + ", ".join(unresolved)
        )

    for samn, path in todo:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(records[samn], handle, indent=2, sort_keys=True)
            handle.write("\n")
    counts = {}
    for record in records.values():
        source = record.get("fetch_source", "ncbi")
        counts[source] = counts.get(source, 0) + 1
    LOGGER.info("wrote %d BioSample records (sources: %s)", len(todo), counts)


if __name__ == "__main__":
    main()
