"""Resolve BioProjects to PubMed and fetch paper text from Europe PMC."""

import json
import os
import re
import time
from pathlib import Path

from http_utils import get

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_FULLTEXT_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)

RATE_LIMIT_SECONDS = 0.35


def _strip_tags(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _bioproject_uid(prjna, email, api_key):
    """ELink needs NCBI's internal UID, not the PRJNA accession."""
    params = {
        "db": "bioproject",
        "term": prjna,
        "retmode": "json",
        "tool": "sra-peco",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    time.sleep(RATE_LIMIT_SECONDS)
    response = get(ESEARCH_URL, params=params)
    ids = response.json().get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


def _linked_pmids(prjna, email, api_key):
    uid = _bioproject_uid(prjna, email, api_key)
    if uid is None:
        return []

    params = {
        "dbfrom": "bioproject",
        "db": "pubmed",
        "id": uid,
        "retmode": "json",
        "tool": "sra-peco",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key
    time.sleep(RATE_LIMIT_SECONDS)
    response = get(ELINK_URL, params=params)
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"ELink failed for {prjna}: {payload['error']}")

    pmids = []
    for linkset in payload.get("linksets", []):
        linksetdbs = linkset.get("linksetdbs", [])
        for identifier in linkset.get("ids", []):
            if isinstance(identifier, dict):
                linksetdbs = linksetdbs + identifier.get("linksetdbs", [])
        for linksetdb in linksetdbs:
            if linksetdb.get("dbto") == "pubmed":
                pmids.extend(str(pmid) for pmid in linksetdb.get("links", []))
    return list(dict.fromkeys(pmids))


def _paper_record(prjna, pmid):
    params = {
        "query": f"EXT_ID:{pmid} AND SRC:MED",
        "resultType": "core",
        "format": "json",
    }
    time.sleep(RATE_LIMIT_SECONDS)
    response = get(EPMC_SEARCH_URL, params=params)
    results = response.json().get("resultList", {}).get("result", [])
    if not results:
        return {"prjna": prjna, "pmid": pmid, "status": "none"}

    hit = results[0]
    pmcid = hit.get("pmcid")
    is_open = str(hit.get("isOpenAccess", "N")).upper() == "Y"
    record = {
        "prjna": prjna,
        "pmid": pmid,
        "pmcid": pmcid,
        "title": hit.get("title"),
        "journal": hit.get("journalTitle"),
        "year": hit.get("pubYear"),
        "is_open_access": is_open,
        "abstract": _strip_tags(hit.get("abstractText")),
        "fulltext_xml": None,
        "status": "abstract",
    }
    if pmcid and is_open:
        time.sleep(RATE_LIMIT_SECONDS)
        fulltext = get(EPMC_FULLTEXT_URL.format(pmcid=pmcid))
        if fulltext is not None:
            record["fulltext_xml"] = fulltext.text
            record["status"] = "fulltext"
    return record


from script_logging import setup as _setup

LOGGER = _setup("fetch_paper")


def main():
    prjnas = list(snakemake.params.prjnas)
    outputs = list(snakemake.output)
    if len(prjnas) != len(outputs):
        raise RuntimeError("PRJNA list and output list differ in length")

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")

    # Existing outputs are kept: with window batching, later windows re-declare
    # projects fetched by earlier windows, and those fetches must be no-ops.
    pending = [
        (prjna, path) for prjna, path in zip(prjnas, outputs) if not Path(path).exists()
    ]

    LOGGER.info(
        "paper fetch: %d projects (%d already cached)",
        len(prjnas),
        len(prjnas) - len(pending),
    )

    for prjna, path in pending:
        pmids = _linked_pmids(prjna, email, api_key)
        if pmids:
            record = _paper_record(prjna, pmids[0])
            record["pmids"] = pmids
        else:
            record = {"prjna": prjna, "pmid": None, "pmids": [], "status": "none"}

        if record["status"] == "none" and not pmids:
            LOGGER.info("%s: no linked publication", prjna)
        else:
            LOGGER.info("%s: %s via PMID %s", prjna, record["status"], record["pmid"])

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")

    LOGGER.info(
        "done: %d fetched, %d already cached", len(pending), len(prjnas) - len(pending)
    )


if __name__ == "__main__":
    main()
