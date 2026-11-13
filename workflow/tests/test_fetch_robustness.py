"""Robustness of the NCBI/Europe PMC fetchers.

Two deterministic failures blocked a whole window (runs 25,001-30,000) before
any labeling ran: a GEO-brokered SRA record whose ``xsi:`` attribute made
ElementTree raise ``unbound prefix``, and a PMC id whose full-text endpoint
returned an error. Fetches must degrade to ENA fallbacks or stubs, never fail
the window.
"""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_paper
import fetch_sra_metadata

import ncbi


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


GEO_RECORD = b"""<EXPERIMENT_PACKAGE_SET xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<EXPERIMENT_PACKAGE>
  <EXPERIMENT accession="SRX1"><TITLE>t</TITLE></EXPERIMENT>
  <RUN accession="SRR1"/>
  <SUBMISSION xsi:noNamespaceSchemaLocation="SRA.submission.xsd"/>
</EXPERIMENT_PACKAGE>
</EXPERIMENT_PACKAGE_SET>"""


def test_strip_namespaces_removes_attribute_prefixes():
    softened = ncbi.strip_namespaces(GEO_RECORD)
    assert b"xsi:" not in softened
    assert b"noNamespaceSchemaLocation" in softened
    import xml.etree.ElementTree as ET

    root = ET.fromstring(softened)
    assert root.find(".//SUBMISSION") is not None


def test_parse_efetch_accepts_geo_attribute_records():
    records, failures = ncbi.parse_efetch(
        GEO_RECORD, fetch_sra_metadata._parse, "EXPERIMENT_PACKAGE"
    )
    assert failures == 0
    assert "SRR1" in records


def test_parse_efetch_salvages_valid_records_when_one_is_broken():
    broken = (
        b"<R>"
        b'<EXPERIMENT_PACKAGE><EXPERIMENT accession="SRX1"/><RUN accession="SRR1"/></EXPERIMENT_PACKAGE>'
        b'<EXPERIMENT_PACKAGE><EXPERIMENT accession="SRX2"/><RUN accession="SRR2"><BROKEN></EXPERIMENT_PACKAGE>'
        b"</R>"
    )
    records, failures = ncbi.parse_efetch(
        broken, fetch_sra_metadata._parse, "EXPERIMENT_PACKAGE"
    )
    assert failures == 1
    assert "SRR1" in records
    assert "SRX2" not in records


def test_fulltext_error_degrades_to_the_abstract(monkeypatch):
    def fake_get(url, **kwargs):
        if "search" in url:
            return _Response(
                {
                    "resultList": {
                        "result": [
                            {
                                "pmcid": "PMC13591405",
                                "isOpenAccess": "Y",
                                "abstractText": "an abstract",
                                "title": "A paper",
                            }
                        ]
                    }
                }
            )
        raise RuntimeError("GET fullTextXML exhausted retries")

    monkeypatch.setattr(fetch_paper, "get", fake_get)
    record = fetch_paper._paper_record("PRJEB1", "123")
    assert record["status"] == "abstract"
    assert record["fulltext_xml"] is None
    assert "exhausted retries" in record["fulltext_error"]


def test_one_bad_project_does_not_fail_the_fetch(tmp_path, monkeypatch):
    good = tmp_path / "PRJNA2.json"
    bad = tmp_path / "PRJNA1.json"

    def fake_fetch(prjna, email, api_key, discover_accession, max_pmids):
        if prjna == "PRJNA1":
            raise RuntimeError("boom")
        return {"prjna": prjna, "pmid": "9", "status": "abstract", "version": 2}

    monkeypatch.setattr(fetch_paper, "_fetch_one", fake_fetch)
    monkeypatch.setattr(
        fetch_paper,
        "snakemake",
        types.SimpleNamespace(
            output=[str(bad), str(good)],
            params=types.SimpleNamespace(
                prjnas=["PRJNA1", "PRJNA2"],
                email="x@example.com",
                api_key_env="",
                discover_by_accession=False,
                max_pmids=1,
            ),
        ),
        raising=False,
    )
    fetch_paper.main()

    stub = json.loads(bad.read_text())
    assert stub["status"] == "error"
    assert "boom" in stub["error"]
    assert json.loads(good.read_text())["status"] == "abstract"
