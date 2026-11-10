"""Skip-if-exists behavior for the single-job metadata fetchers.

With window batching, later windows re-declare accessions fetched by earlier
windows; the fetchers must treat existing outputs as done and fetch only the
remaining accessions.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _snakemake(outputs=None, **params):
    return SimpleNamespace(output=list(outputs or []), params=SimpleNamespace(**params))


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_fetch_biosample_skips_existing(tmp_path, monkeypatch):
    import fetch_biosample

    existing = tmp_path / "results/metadata/biosample/SAMN1.json"
    _write(existing, {"accession": "SAMN1", "organism": "from-disk"})
    missing = tmp_path / "results/metadata/biosample/SAMN2.json"

    calls = []

    def fake_efetch(db, ids, *args, **kwargs):
        calls.append((db, tuple(ids)))
        return b"<root><BioSample accession='SAMN2'><Organism><OrganismName>X</OrganismName></Organism></BioSample></root>"

    monkeypatch.setattr(fetch_biosample, "fetch_efetch", fake_efetch)
    monkeypatch.setattr(
        fetch_biosample,
        "snakemake",
        _snakemake(
            samns=["SAMN1", "SAMN2"],
            outputs=[str(existing), str(missing)],
            email="x@example.com",
            api_key_env="",
            batch_size=10,
            max_retries=1,
        ),
        raising=False,
    )
    fetch_biosample.main()

    assert calls == [("biosample", ("SAMN2",))]
    assert json.loads(existing.read_text())["organism"] == "from-disk"
    assert json.loads(missing.read_text())["organism"] == "X"


def test_fetch_sra_metadata_skips_existing(tmp_path, monkeypatch):
    import fetch_sra_metadata

    existing = tmp_path / "results/metadata/sra/SRR1.json"
    _write(existing, {"run": "SRR1", "experiment_title": "from-disk"})
    missing = tmp_path / "results/metadata/sra/SRR2.json"

    calls = []

    def fake_efetch(db, ids, *args, **kwargs):
        calls.append(tuple(ids))
        return (
            b"<root><EXPERIMENT_PACKAGE><EXPERIMENT accession='SRX1'>"
            b"<TITLE>t</TITLE></EXPERIMENT>"
            b"<RUN accession='SRR2'/></EXPERIMENT_PACKAGE></root>"
        )

    monkeypatch.setattr(fetch_sra_metadata, "fetch_efetch", fake_efetch)
    monkeypatch.setattr(
        fetch_sra_metadata,
        "snakemake",
        _snakemake(
            runs=["SRR1", "SRR2"],
            outputs=[str(existing), str(missing)],
            email="x@example.com",
            api_key_env="",
            batch_size=10,
            max_retries=1,
        ),
        raising=False,
    )
    fetch_sra_metadata.main()

    assert calls == [("SRR2",)]
    assert json.loads(existing.read_text())["experiment_title"] == "from-disk"
    assert json.loads(missing.read_text())["run"] == "SRR2"


def test_fetch_paper_skips_existing(tmp_path, monkeypatch):
    import fetch_paper

    existing = tmp_path / "results/metadata/paper/PRJNA1.json"
    _write(
        existing,
        {
            "prjna": "PRJNA1",
            "status": "from-disk",
            "version": fetch_paper.FETCH_VERSION,
        },
    )
    missing = tmp_path / "results/metadata/paper/PRJNA2.json"

    linked = []
    records = []

    def fake_linked(prjna, email, api_key):
        linked.append(prjna)
        return ["123"]

    def fake_record(prjna, pmid):
        records.append(prjna)
        return {"prjna": prjna, "pmid": pmid, "status": "abstract"}

    monkeypatch.setattr(fetch_paper, "_linked_pmids", fake_linked)
    monkeypatch.setattr(fetch_paper, "_paper_record", fake_record)
    monkeypatch.setattr(
        fetch_paper,
        "snakemake",
        _snakemake(
            prjnas=["PRJNA1", "PRJNA2"],
            outputs=[str(existing), str(missing)],
            email="x@example.com",
            api_key_env="",
            discover_by_accession=False,
            max_pmids=1,
        ),
        raising=False,
    )
    fetch_paper.main()

    assert linked == ["PRJNA2"]
    assert records == ["PRJNA2"]
    assert json.loads(existing.read_text())["status"] == "from-disk"
    assert json.loads(missing.read_text())["pmid"] == "123"


def test_fetch_bioproject_skips_existing(tmp_path, monkeypatch):
    import fetch_bioproject

    existing = tmp_path / "results/metadata/bioproject/PRJNA1.json"
    _write(existing, {"prjna": "PRJNA1", "status": "from-disk"})
    missing = tmp_path / "results/metadata/bioproject/PRJNA2.json"

    searched = []

    def fake_uid(prjna, email, api_key):
        searched.append(prjna)
        return "555"

    monkeypatch.setattr(fetch_bioproject, "_search_uid", fake_uid)
    monkeypatch.setattr(
        fetch_bioproject,
        "_parse",
        lambda xml_bytes, prjna=None: {"prjna": prjna, "status": "ok"},
    )
    monkeypatch.setattr(
        fetch_bioproject,
        "snakemake",
        _snakemake(
            prjnas=["PRJNA1", "PRJNA2"],
            outputs=[str(existing), str(missing)],
            email="x@example.com",
            api_key_env="",
            max_retries=1,
        ),
        raising=False,
    )
    fetch_bioproject.main()

    assert searched == ["PRJNA2"]
    assert json.loads(existing.read_text())["status"] == "from-disk"
    assert json.loads(missing.read_text())["status"] == "ok"


def test_athrdb_cap_stale_only_with_budget():
    import fetch_athrdb

    stub = fetch_athrdb.stub("SRR1", note="request_cap_reached")
    assert fetch_athrdb.cap_stale(stub, 0) is False
    assert fetch_athrdb.cap_stale(stub, 3) is True
    assert fetch_athrdb.cap_stale({"athrdb_note": "no_geo_record"}, 3) is False
    assert fetch_athrdb.cap_stale(None, 3) is False

    # A no-request-cap workflow (max_requests=0) always has budget.
    assert fetch_athrdb.cap_stale(stub, 1) is True


def test_athrdb_cap_stub_never_written_for_non_arabidopsis():
    import fetch_athrdb

    record = fetch_athrdb._classify("SRR1", "Zea mays", True, True)
    assert record["athrdb_note"] == "non_arabidopsis_species"
    disabled = fetch_athrdb._classify("SRR2", "Arabidopsis thaliana", False, True)
    assert disabled["athrdb_note"] == "athrdb_disabled"
