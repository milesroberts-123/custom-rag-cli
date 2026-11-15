"""Tests for the ENA BioSample fallback in fetch_biosample."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_biosample

ENA_FIXTURE = Path(__file__).parent / "fixtures" / "ena_sample.xml"


def test_parse_ena_sample_fixture():
    record = fetch_biosample.parse_ena_sample(ENA_FIXTURE.read_bytes())
    assert record["accession"] == "SAMEA112139654"
    assert record["organism"] == "Arabidopsis thaliana"
    assert record["fetch_source"] == "ena"
    attributes = record["attributes"]
    assert attributes["cultivar"] == "Columbia"
    assert attributes["isolate"] == "not applicable"
    assert "ENA-CHECKLIST" in attributes


def test_parse_ena_sample_without_sample():
    assert fetch_biosample.parse_ena_sample(b"<SAMPLE_SET/>") is None


def test_ncbi_records_carry_source(tmp_path, monkeypatch):
    import fetch_biosample

    calls = []

    def fake_efetch(db, ids, *args, **kwargs):
        calls.append(tuple(ids))
        return (
            b"<root><BioSample accession='SAMN1'>"
            b"<Organism><OrganismName>X</OrganismName></Organism>"
            b"</BioSample></root>"
        )

    monkeypatch.setattr(fetch_biosample, "fetch_efetch", fake_efetch)
    # No ENA calls should happen: NCBI returned the record.
    monkeypatch.setattr(
        fetch_biosample,
        "_ena_record",
        lambda accession: pytest.fail(f"unexpected ENA call for {accession}"),
    )
    output = tmp_path / "results/metadata/biosample/SAMN1.json"
    monkeypatch.setattr(
        fetch_biosample,
        "snakemake",
        SimpleNamespace(
            output=[str(output)],
            params=SimpleNamespace(
                samns=["SAMN1"],
                email="x@example.com",
                api_key_env="",
                batch_size=10,
                max_retries=1,
                ena_batch_size=100,
            ),
        ),
        raising=False,
    )
    fetch_biosample.main()

    record = json.loads(output.read_text())
    assert record["organism"] == "X"
    assert record["fetch_source"] == "ncbi"
    assert calls == [("SAMN1",)]


def test_ena_fallback(tmp_path, monkeypatch, caplog):
    import logging

    import fetch_biosample

    with caplog.at_level(logging.INFO, logger="fetch_biosample"):
        ncbi_calls = []

        def fake_efetch(db, ids, *args, **kwargs):
            ncbi_calls.append(tuple(ids))
            # NCBI has nothing for these: mirror miss.
            return b"<BioSampleSet></BioSampleSet>"

        monkeypatch.setattr(fetch_biosample, "fetch_efetch", fake_efetch)
        ena_calls = []

        def fake_ena(accessions):
            ena_calls.append(list(accessions))
            record = fetch_biosample.parse_ena_sample(ENA_FIXTURE.read_bytes())
            return {
                accession: dict(record, accession=accession) for accession in accessions
            }

        monkeypatch.setattr(fetch_biosample, "_ena_request", fake_ena)
        output = tmp_path / "results/metadata/biosample/SAMEA112139654.json"
        monkeypatch.setattr(
            fetch_biosample,
            "snakemake",
            SimpleNamespace(
                output=[str(output)],
                params=SimpleNamespace(
                    samns=["SAMEA112139654"],
                    email="x@example.com",
                    api_key_env="",
                    batch_size=10,
                    max_retries=1,
                    ena_batch_size=100,
                ),
            ),
            raising=False,
        )
        fetch_biosample.main()

    record = json.loads(output.read_text())
    assert record["fetch_source"] == "ena"
    assert record["attributes"]["cultivar"] == "Columbia"
    assert ncbi_calls == [("SAMEA112139654",)]
    assert ena_calls == [["SAMEA112139654"]]
    messages = [entry.message for entry in caplog.records]
    assert any("falling back to ENA" in message for message in messages)
    assert any(
        "ENA fallback: 1 of 1 accessions recovered" in message for message in messages
    )


def test_both_sources_missing_raises(tmp_path, monkeypatch):
    import fetch_biosample

    monkeypatch.setattr(
        fetch_biosample,
        "fetch_efetch",
        lambda *args, **kwargs: b"<BioSampleSet></BioSampleSet>",
    )
    monkeypatch.setattr(fetch_biosample, "_ena_request", lambda accessions: None)
    output = tmp_path / "results/metadata/biosample/SAMEA9.json"
    monkeypatch.setattr(
        fetch_biosample,
        "snakemake",
        SimpleNamespace(
            output=[str(output)],
            params=SimpleNamespace(
                samns=["SAMEA9"],
                email="x@example.com",
                api_key_env="",
                batch_size=10,
                max_retries=1,
                ena_batch_size=100,
            ),
        ),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="NCBI or ENA"):
        fetch_biosample.main()


def test_ena_fallback_skips_existing_outputs(tmp_path, monkeypatch):
    import fetch_biosample

    existing = tmp_path / "results/metadata/biosample/SAMEA112139654.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(json.dumps({"accession": "SAMEA112139654", "kept": True}))
    output = tmp_path / "results/metadata/biosample/SAMEA112139655.json"

    monkeypatch.setattr(
        fetch_biosample,
        "fetch_efetch",
        lambda *args, **kwargs: b"<BioSampleSet></BioSampleSet>",
    )

    def fake_ena(accessions):
        assert list(accessions) == ["SAMEA112139655"]
        return {
            "SAMEA112139655": {
                "accession": "SAMEA112139655",
                "organism": "ena",
                "attributes": {},
                "fetch_source": "ena",
            }
        }

    monkeypatch.setattr(fetch_biosample, "_ena_request", fake_ena)
    monkeypatch.setattr(
        fetch_biosample,
        "snakemake",
        SimpleNamespace(
            output=[str(existing), str(output)],
            params=SimpleNamespace(
                samns=["SAMEA112139654", "SAMEA112139655"],
                email="x@example.com",
                api_key_env="",
                batch_size=10,
                max_retries=1,
                ena_batch_size=100,
            ),
        ),
        raising=False,
    )
    fetch_biosample.main()

    assert json.loads(existing.read_text()) == {
        "accession": "SAMEA112139654",
        "kept": True,
    }
    record = json.loads(output.read_text())
    assert record["fetch_source"] == "ena"


MINI_SET = b"""<?xml version="1.0"?>
<SAMPLE_SET>
  <SAMPLE accession="SAMEA1"><SAMPLE_NAME><SCIENTIFIC_NAME>Arabidopsis</SCIENTIFIC_NAME></SAMPLE_NAME>
    <SAMPLE_ATTRIBUTES><SAMPLE_ATTRIBUTE><TAG>cultivar</TAG><VALUE>Col-0</VALUE></SAMPLE_ATTRIBUTE></SAMPLE_ATTRIBUTES>
  </SAMPLE>
  <SAMPLE accession="SAMEA2"><SAMPLE_NAME><SCIENTIFIC_NAME>Arabidopsis</SCIENTIFIC_NAME></SAMPLE_NAME>
  </SAMPLE>
</SAMPLE_SET>"""


def test_parse_ena_sample_set_reads_every_sample():
    records = fetch_biosample.parse_ena_sample_set(MINI_SET)
    assert set(records) == {"SAMEA1", "SAMEA2"}
    assert records["SAMEA1"]["attributes"]["cultivar"] == "Col-0"


def test_ena_records_batches_requests(monkeypatch):
    calls = []

    def fake_request(accessions):
        calls.append(list(accessions))
        return {
            a: {"accession": a, "attributes": {}, "fetch_source": "ena"}
            for a in accessions
        }

    monkeypatch.setattr(fetch_biosample, "_ena_request", fake_request)
    records = fetch_biosample._ena_records(["A1", "A2", "A3"], batch_size=2)
    assert set(records) == {"A1", "A2", "A3"}
    assert calls == [["A1", "A2"], ["A3"]]


def test_ena_records_split_a_failed_batch(monkeypatch):
    calls = []

    def fake_request(accessions):
        calls.append(list(accessions))
        if len(accessions) > 1:
            return None  # e.g. HTTP 400 on the combined request
        return {accessions[0]: {"accession": accessions[0], "attributes": {}}}

    monkeypatch.setattr(fetch_biosample, "_ena_request", fake_request)
    records = fetch_biosample._ena_records(["A1", "A2"], batch_size=2)
    assert set(records) == {"A1", "A2"}
    assert calls == [["A1", "A2"], ["A1"], ["A2"]]


def test_ena_records_retries_accessions_missing_from_a_batch(monkeypatch):
    def fake_request(accessions):
        if len(accessions) > 1:
            return {accessions[0]: {"accession": accessions[0], "attributes": {}}}
        return {accessions[0]: {"accession": accessions[0], "attributes": {}}}

    monkeypatch.setattr(fetch_biosample, "_ena_request", fake_request)
    records = fetch_biosample._ena_records(["A1", "A2"], batch_size=2)
    assert set(records) == {"A1", "A2"}
