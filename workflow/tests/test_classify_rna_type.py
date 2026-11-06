"""Tests for the RNA type classifier."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate
import classify_rna_type as rna

KEYS = ["rna type", "rna_type", "library type", "library preparation"]


def _classify(biosample=None, sra=None):
    return rna._classify_rules(biosample or {}, sra or {}, KEYS)


def test_polya_selection_is_mrna():
    category, subtype, evidence = _classify(
        sra={"library_strategy": "RNA-Seq", "library_selection": "PolyA"}
    )
    assert category == rna.MRNA
    assert subtype is None
    assert "PolyA" in evidence

    category, _, _ = _classify(
        sra={"library_strategy": "RNA-Seq", "library_selection": "poly(A)"}
    )
    assert category == rna.MRNA

    category, _, _ = _classify(
        sra={"library_strategy": "RNA-Seq", "library_selection": "oligo(dT)"}
    )
    assert category == rna.MRNA


def test_ribozero_is_ribo_depleted_total_rna():
    category, subtype, evidence = _classify(
        sra={"library_strategy": "RNA-Seq", "library_selection": "RiboZero"}
    )
    assert category == rna.RIBO
    assert subtype is None
    assert "RiboZero" in evidence


def test_mirna_strategy_is_small_rna_subtype():
    category, subtype, _ = _classify(sra={"library_strategy": "miRNA-Seq"})
    assert category == rna.SMALL
    assert subtype == "mirna"


def test_biosample_total_rna():
    category, _, _ = _classify(
        biosample={
            "attributes": {"rna type": "total RNA"},
        },
        sra={"library_strategy": "RNA-Seq"},
    )
    assert category == rna.TOTAL


def test_total_rna_input_does_not_override_polya_selection():
    category, _, _ = _classify(
        sra={
            "library_strategy": "RNA-Seq",
            "library_selection": "PolyA",
            "library_construction_protocol": "Total RNA was extracted, then polyA selected.",
        }
    )
    assert category == rna.MRNA


def test_cdna_without_selection_is_ambiguous():
    assert (
        _classify(sra={"library_strategy": "RNA-Seq", "library_selection": "cDNA"})
        is None
    )


def test_conflicting_signals_are_unknown():
    category, subtype, _ = _classify(
        sra={"library_strategy": "miRNA-Seq", "library_selection": "PolyA"}
    )
    assert category == rna.UNKNOWN
    assert subtype is None


def test_wgs_is_not_rna():
    category, _, _ = _classify(sra={"library_strategy": "WGS"})
    assert category == rna.NOT_RNA


def test_ncrna_strategy_is_other_rna():
    category, _, _ = _classify(sra={"library_strategy": "ncRNA-Seq"})
    assert category == rna.OTHER


def test_rrna_depletion_does_not_become_small_rna():
    category, subtype, _ = _classify(
        biosample={"attributes": {"rna type": "total RNA, rRNA depleted"}},
        sra={"library_strategy": "RNA-Seq", "library_selection": "RiboZero"},
    )
    assert category == rna.RIBO
    assert subtype is None


def test_main_writes_classification(tmp_path, monkeypatch):
    metadata = tmp_path / "results" / "metadata"
    (metadata / "biosample").mkdir(parents=True)
    (metadata / "sra").mkdir(parents=True)
    (metadata / "biosample" / "SAMN1.json").write_text(json.dumps({"attributes": {}}))
    (metadata / "sra" / "SRR1.json").write_text(
        json.dumps({"library_strategy": "RNA-Seq", "library_selection": "RiboZero"})
    )
    marker_path = tmp_path / "results" / "chunks" / "rna_type" / "0.done"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        rna,
        "snakemake",
        SimpleNamespace(
            output=[str(marker_path)],
            params={
                "runs": [["SRR1"]],
                "samns": ["SAMN1"],
                "backend": "rules",
                "attribute_keys": KEYS,
                "accepted_rna_types": [rna.MRNA, rna.RIBO],
                "min_confidence": 0.6,
                "server_url": "",
                "api_key": "",
                "decision_model": "",
                "model": "",
                "model_params": {},
            },
        ),
        raising=False,
    )
    rna.main()

    output_path = tmp_path / "results" / "rna_type" / "SAMN1.json"
    result = json.loads(output_path.read_text())
    assert result["rna_type"] == rna.RIBO
    assert result["ribo_depleted"] is True
    assert result["mrna_eligible"] is True
    assert result["source"] == "rules"
    assert json.loads(marker_path.read_text())["samples"] == 1


def test_classify_one_conflict_is_unknown():
    params = {
        "attribute_keys": KEYS,
        "backend": "rules",
        "accepted_rna_types": [rna.MRNA, rna.RIBO],
        "min_confidence": 0.6,
    }
    result = rna._classify_one(
        "SAMN1",
        "SRR1",
        {"attributes": {}},
        {"library_strategy": "miRNA-Seq", "library_selection": "PolyA"},
        params,
    )
    assert result["rna_type"] == rna.UNKNOWN
    assert result["source"] == "rules_conflict"
    assert result["mrna_eligible"] is False


def test_classify_one_missing_metadata_is_unknown():
    params = {
        "attribute_keys": KEYS,
        "backend": "rules",
        "accepted_rna_types": [rna.MRNA, rna.RIBO],
        "min_confidence": 0.6,
    }
    result = rna._classify_one(
        "SAMN2",
        "SRR2",
        {"attributes": {}},
        {"library_strategy": "RNA-Seq"},
        params,
    )
    assert result["rna_type"] == rna.UNKNOWN
    assert result["source"] == "missing_metadata"


def test_exclusion_reasons():
    assert aggregate._exclusion_reason({"rna_type": "unknown"}) == "rna_type_unknown"
    assert aggregate._exclusion_reason({"rna_type": "not_rna"}) == "not_rna_assay"
    assert (
        aggregate._exclusion_reason({"rna_type": "total_rna"})
        == "rna_type_total_rna_not_accepted"
    )
