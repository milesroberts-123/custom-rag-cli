"""Fetch BioProject records from NCBI and store one JSON file per project."""

import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from http_utils import get
from ncbi import fetch_efetch, strip_namespaces

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
RATE_LIMIT_SECONDS = 0.35


def _text(element, path, default=None):
    node = element.find(path)
    if node is None or node.text is None:
        return default
    value = node.text.strip()
    return value or default


def _attributes(element, path):
    node = element.find(path)
    return dict(node.attrib) if node is not None else {}


def _search_uid(prjna, email, api_key):
    """Resolve a PRJNA accession to the internal BioProject UID."""
    params = {
        "db": "bioproject",
        "term": prjna,
        "retmode": "json",
        "tool": "sra-peco",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    response = get(ESEARCH_URL, params=params)
    if response is None:
        return None
    ids = response.json().get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


def _parse(xml_bytes, prjna=None):
    """Parse a BioProject efetch response into a compact record."""
    root = ET.fromstring(strip_namespaces(xml_bytes))
    summary = root.find(".//DocumentSummary")
    if summary is None:
        return {"prjna": prjna, "status": "none"}

    project = summary.find("Project")
    if project is None:
        return {"prjna": prjna, "status": "none"}

    archive = project.find("ProjectID/ArchiveID")
    accession = archive.get("accession") if archive is not None else prjna
    uid = summary.get("uid") or (archive.get("id") if archive is not None else None)

    data_types = [
        (node.text or "").strip()
        for node in project.findall(".//IntendedDataTypeSet/DataType")
        if (node.text or "").strip()
    ]
    objectives = [
        dict(node.attrib)
        for node in project.findall(".//Objectives/Data")
        if node.attrib
    ]
    grant = project.find("ProjectDescr/Grant")
    grant_record = None
    if grant is not None:
        grant_record = {
            "grant_id": grant.get("GrantId"),
            "title": _text(grant, "Title"),
            "agency": _text(grant, "Agency"),
        }
    submission = summary.find("Submission")

    return {
        "prjna": prjna or accession,
        "uid": uid,
        "accession": accession,
        "local_ids": [
            (node.text or "").strip()
            for node in project.findall("ProjectID/LocalID")
            if (node.text or "").strip()
        ],
        "title": _text(project, "ProjectDescr/Title"),
        "description": _text(project, "ProjectDescr/Description"),
        "organism": _text(project, "ProjectDescr/Organism/OrganismName"),
        "relevance": _text(project, "ProjectDescr/Relevance/Environmental"),
        "grant": grant_record,
        "project_type": {
            "target": _attributes(project, "ProjectType/ProjectTypeSubmission/Target"),
            "method": _attributes(project, "ProjectType/ProjectTypeSubmission/Method"),
            "objectives": objectives,
            "data_types": data_types,
        },
        "submission": {
            "last_update": submission.get("last_update")
            if submission is not None
            else None,
            "submission_id": submission.get("submission_id")
            if submission is not None
            else None,
            "submitted": submission.get("submitted")
            if submission is not None
            else None,
            "organization": _text(summary, "Submission/Description/Organization/Name"),
            "access": _text(summary, "Submission/Description/Access"),
        },
        "status": "ok",
    }


def main():
    prjnas = list(snakemake.params.prjnas)
    outputs = list(snakemake.output)
    if len(prjnas) != len(outputs):
        raise RuntimeError("PRJNA list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    max_retries = int(snakemake.params.max_retries)

    # Existing outputs are kept: with window batching, later windows re-declare
    # projects fetched by earlier windows, and those fetches must be no-ops.
    pending = [
        (prjna, path) for prjna, path in zip(prjnas, outputs) if not Path(path).exists()
    ]

    for index, (prjna, path) in enumerate(pending):
        if index:
            time.sleep(RATE_LIMIT_SECONDS)
        uid = _search_uid(prjna, email, api_key)
        if not uid:
            record = {"prjna": prjna, "status": "none"}
        else:
            time.sleep(RATE_LIMIT_SECONDS)
            xml_bytes = fetch_efetch(
                "bioproject",
                [uid],
                email,
                api_key,
                max_retries,
                error_label=f"BioProject fetch for {prjna}",
            )
            record = _parse(xml_bytes, prjna)
            record["uid"] = uid

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
