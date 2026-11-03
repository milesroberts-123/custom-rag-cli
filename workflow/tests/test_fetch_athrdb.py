"""Tests for the PlantRNADB (ATHRDB) fetch script."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_athrdb as athrdb

FIXTURE = Path(__file__).parent / "fixtures" / "athrdb_gsm3181995.html"


def test_parse_fixture():
    parsed = athrdb.parse_athrdb_html(FIXTURE.read_text())
    assert parsed["gsm"] == "GSM3181995"
    assert parsed["athrdb_tissue"] == "root"
    assert parsed["athrdb_genotype"] == "wild type"
    assert parsed["athrdb_ecotype"] == "Col-0"
    assert parsed["athrdb_project"] == "PRJNA475464"
    assert parsed["athrdb_title"] == "ROOT ZONE I (0.5mm) REP 1 [RNA-seq]"
    assert parsed["athrdb_total_reads"] == 14653862
    assert parsed["athrdb_mapped_rate"] == 0.6428
    assert parsed["athrdb_release_date"] == "2018/10/29"


def test_parse_pages_without_curation():
    assert athrdb.parse_athrdb_html("") is None
    assert athrdb.parse_athrdb_html("<div>No data</div>") is None
    assert athrdb.parse_athrdb_html("<table class='info'><td>a</td></table>") is None


def test_parse_requires_matching_gsm():
    page = (
        "<table class='info'><tr><td>GSM111</td><td>title</td>"
        "<td>1,000</td><td>50%</td></tr></table>"
        "<table class='info'><tr><td>GSM222 to NCBI</td><td>root</td>"
        "<td>wild type</td><td>Col-0</td><td>PRJNA1</td><td>2020/01/01</td></tr></table>"
    )
    assert athrdb.parse_athrdb_html(page) is None


def test_gsm_from_summaries():
    result = {
        "uids": ["1", "2"],
        "1": {"entrytype": "GSE", "accession": "GSE123"},
        "2": {"entrytype": "GSM", "accession": "GSM1662397"},
    }
    assert athrdb.gsm_from_summaries(result) == "GSM1662397"
    gse_only = {"uids": ["1"], "1": {"entrytype": "GSE", "accession": "GSE123"}}
    assert athrdb.gsm_from_summaries(gse_only) is None
    assert athrdb.gsm_from_summaries({"uids": []}) is None


def test_is_arabidopsis():
    assert athrdb.is_arabidopsis("Arabidopsis thaliana")
    assert athrdb.is_arabidopsis("Arabidopsis_thaliana ")
    assert not athrdb.is_arabidopsis("Arabidopsis lyrata")
    assert not athrdb.is_arabidopsis("")
    assert not athrdb.is_arabidopsis(None)


def test_pacer_enforces_minimum_interval():
    now = [0.0]
    slept = []
    pacer = athrdb.RequestPacer(
        2.0, clock=lambda: now[0], sleeper=lambda seconds: slept.append(seconds)
    )
    pacer.wait()
    now[0] = 0.5
    pacer.wait()
    assert slept == [1.5]
    now[0] = 10.0
    pacer.wait()
    assert slept == [1.5]


class FakeSession:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return SimpleNamespace(
            status_code=self.status_code,
            raise_for_status=lambda: None,
            text=self.text,
        )


def test_client_builds_search_url_and_parses():
    session = FakeSession(FIXTURE.read_text())
    client = athrdb.AthrdbClient(
        "https://plantrnadb.com/athrdb/Search.php", 0.0, 10, session=session
    )
    parsed = client.fetch_library("GSM3181995")
    assert parsed["gsm"] == "GSM3181995"
    assert session.urls == [
        "https://plantrnadb.com/athrdb/Search.php?query=GSM3181995/0/max/NAN/NAN/NAN/"
    ]


def test_classify_rules_order():
    assert athrdb._classify("SRR1", "Arabidopsis thaliana", True, False) is None
    disabled = athrdb._classify("SRR1", "Arabidopsis thaliana", False, False)
    assert disabled["athrdb_note"] == "athrdb_disabled"
    other = athrdb._classify("SRR2", "Zea mays", True, False)
    assert other["athrdb_note"] == "non_arabidopsis_species"
    capped = athrdb._classify("SRR3", "Arabidopsis thaliana", True, True)
    assert capped["athrdb_note"] == "request_cap_reached"
    assert capped["athrdb_queried"] is False
