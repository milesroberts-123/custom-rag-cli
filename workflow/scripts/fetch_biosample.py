"""Fetch BioSample records from NCBI and store normalized per-sample JSON."""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from ncbi import fetch_efetch, strip_namespaces


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
        }
    return records


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

    records = {}
    for start in range(0, len(todo), batch_size):
        batch = todo[start : start + batch_size]
        records.update(
            _parse(
                fetch_efetch(
                    "biosample",
                    [samn for samn, _ in batch],
                    email,
                    api_key,
                    max_retries,
                    timeout=120,
                    error_label="BioSample fetch",
                )
            )
        )

    missing = [samn for samn, _ in todo if samn not in records]
    if missing:
        raise RuntimeError(
            "NCBI returned no BioSample record for: " + ", ".join(sorted(missing))
        )

    for samn, path in todo:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(records[samn], handle, indent=2, sort_keys=True)
            handle.write("\n")


if __name__ == "__main__":
    main()
