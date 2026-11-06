"""Fetch SRA run metadata and store compact per-run JSON records."""

import csv
import io
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from http_utils import get
from ncbi import fetch_efetch, strip_namespaces

ENA_FILEREPORT = "https://www.ebi.ac.uk/ena/portal/api/filereport"
ENA_FIELDS = (
    "run_accession",
    "experiment_accession",
    "sample_accession",
    "study_accession",
    "library_strategy",
    "library_selection",
    "library_source",
    "library_layout",
    "fastq_ftp",
    "fastq_md5",
    "fastq_bytes",
    "library_name",
    "library_construction_protocol",
    "experiment_title",
    "study_title",
    "sample_title",
)


def _layout(library):
    """Return SINGLE or PAIRED from an SRA LIBRARY_LAYOUT element."""
    if library is None:
        return ""
    node = library.find("LIBRARY_LAYOUT")
    if node is None:
        return ""
    if node.find("PAIRED") is not None:
        return "PAIRED"
    if node.find("SINGLE") is not None:
        return "SINGLE"
    return ""


def _text(element, path):
    node = element.find(path)
    return (node.text or "").strip() if node is not None and node.text else ""


def _parse(xml_bytes):
    root = ET.fromstring(strip_namespaces(xml_bytes))
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

        experiment_attributes = {}
        for attribute in package.findall(".//EXPERIMENT_ATTRIBUTE"):
            tag = _text(attribute, "TAG")
            value = _text(attribute, "VALUE")
            if tag:
                experiment_attributes[tag] = value

        record = {
            "experiment_accession": experiment.get("accession"),
            "experiment_title": _text(experiment, "TITLE"),
            "library_name": (
                _text(library, "LIBRARY_NAME") if library is not None else ""
            ),
            "library_strategy": (
                _text(library, "LIBRARY_STRATEGY") if library is not None else ""
            ),
            "library_selection": (
                _text(library, "LIBRARY_SELECTION") if library is not None else ""
            ),
            "library_source": (
                _text(library, "LIBRARY_SOURCE") if library is not None else ""
            ),
            "library_layout": _layout(library),
            "library_construction_protocol": (
                _text(library, "LIBRARY_CONSTRUCTION_PROTOCOL")
                if library is not None
                else ""
            ),
            "sample_accession": sample.get("accession") if sample is not None else None,
            "sample_name": sample_name,
            "study_accession": study.get("accession") if study is not None else None,
            "study_title": _text(package, ".//STUDY_TITLE"),
            "study_abstract": _text(package, ".//STUDY_ABSTRACT"),
            "sample_attributes": attributes,
            "experiment_attributes": experiment_attributes,
        }
        for run in package.findall(".//RUN"):
            accession = run.get("accession")
            if accession:
                records[accession] = {
                    **record,
                    "run": accession,
                    "fetch_source": "ncbi",
                }
    return records


def _ena_record(accession, timeout=60):
    """Fetch one run's metadata from ENA when NCBI's mirror omits it.

    NCBI efetch db=sra silently drops a few ENA-origin runs from large batches
    (window 1 failed on ERR11343449/ERR11343489 this way) even though both
    esearch and ENA have them. Returns None when ENA has no record either.
    """
    response = get(
        ENA_FILEREPORT,
        params={
            "accession": accession,
            "result": "read_run",
            "fields": ",".join(ENA_FIELDS),
            "format": "tsv",
        },
        timeout=timeout,
    )
    if response is None or not response.ok:
        return None
    rows = list(csv.DictReader(io.StringIO(response.text), delimiter="\t"))
    if not rows:
        return None
    row = rows[0]
    return {
        "run": accession,
        "experiment_accession": row.get("experiment_accession", ""),
        "experiment_title": row.get("experiment_title", ""),
        "library_name": row.get("library_name", ""),
        "library_strategy": row.get("library_strategy", ""),
        "library_selection": row.get("library_selection", ""),
        "library_source": row.get("library_source", ""),
        "library_layout": (row.get("library_layout", "") or "").upper(),
        "fastq_ftp": row.get("fastq_ftp", ""),
        "fastq_md5": row.get("fastq_md5", ""),
        "fastq_bytes": row.get("fastq_bytes", ""),
        "library_construction_protocol": row.get("library_construction_protocol", ""),
        "sample_accession": row.get("sample_accession", ""),
        "sample_name": row.get("sample_title", ""),
        "study_accession": row.get("study_accession", ""),
        "study_title": row.get("study_title", ""),
        "study_abstract": "",
        "sample_attributes": {},
        "experiment_attributes": {},
        "fetch_source": "ena",
    }


from script_logging import setup as _setup

LOGGER = _setup("fetch_sra_metadata")


def main():
    runs = list(snakemake.params.runs)
    outputs = list(snakemake.output)
    if len(runs) != len(outputs):
        raise RuntimeError("run list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    batch_size = int(snakemake.params.batch_size)
    max_retries = int(snakemake.params.max_retries)

    # Existing outputs are kept: with window batching, later windows re-declare
    # runs fetched by earlier windows, and those fetches must be no-ops.
    todo = [(run, path) for run, path in zip(runs, outputs) if not Path(path).exists()]
    LOGGER.info(
        "SRA metadata fetch: %d runs (%d already cached)",
        len(runs),
        len(runs) - len(todo),
    )

    records = {}
    batches = [todo[i : i + batch_size] for i in range(0, len(todo), batch_size)]
    for index, batch in enumerate(batches, start=1):
        LOGGER.info(
            "NCBI efetch db=sra batch %d/%d (%d accessions)",
            index,
            len(batches),
            len(batch),
        )
        records.update(
            _parse(
                fetch_efetch(
                    "sra",
                    [run for run, _ in batch],
                    email,
                    api_key,
                    max_retries,
                    timeout=180,
                    error_label="SRA metadata fetch",
                )
            )
        )
        LOGGER.info(
            "batch %d/%d parsed (%d records total)",
            index,
            len(batches),
            len(records),
        )

    missing = [run for run, _ in todo if run not in records]
    if missing:
        LOGGER.info(
            "NCBI omitted %d run record(s); falling back to ENA: %s",
            len(missing),
            ", ".join(sorted(missing)),
        )
    unresolved = []
    for run in missing:
        record = _ena_record(run)
        if record is None:
            unresolved.append(run)
            continue
        records[run] = record
        LOGGER.info("%s: metadata from ENA fallback", run)

    # A run that neither mirror returns must not fail the whole window: the
    # window also carries thousands of other runs. Store a stub so RNA typing
    # records it as unknown/not eligible and the sample shows up for review.
    for run in unresolved:
        LOGGER.warning("%s: no SRA record in NCBI or ENA; writing a stub", run)
        records[run] = {
            "run": run,
            "fetch_source": "missing",
            "sra_note": "no SRA record in the NCBI or ENA mirrors",
            "library_strategy": "",
            "library_layout": "",
            "library_selection": "",
            "library_source": "",
        }

    for run, path in todo:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(records[run], handle, indent=2, sort_keys=True)
            handle.write("\n")

    LOGGER.info("wrote %d of %d SRA records", len(records), len(runs))


if __name__ == "__main__":
    main()
