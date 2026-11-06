"""Tests for RNA-type filtering and window accumulation in the aggregate rule."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate

REVIEW = {
    "rna_type_confidence": 0.5,
    "tissue_confidence": 0.5,
    "germplasm_confidence": 0.5,
    "exposure_retrieval_score": 0.55,
    "study_confidence": 0.5,
}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _rna(run, rna_type, eligible):
    return {
        "run": run,
        "rna_type": rna_type,
        "rna_subtype": None,
        "ribo_depleted": rna_type == "ribo_depleted_total_rna",
        "mrna_eligible": eligible,
        "confidence": 1.0,
        "source": "rules",
        "evidence": "test",
    }


def test_aggregate_accumulates_completed_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = tmp_path / "results"
    samples = tmp_path / "samples.tsv"
    pd.DataFrame(
        [
            {
                "run": "SRR1",
                "biosample": "SAMN1",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
            },
            {
                "run": "SRR2",
                "biosample": "SAMN2",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
            },
            {
                "run": "SRR3",
                "biosample": "SAMN3",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
            },
        ]
    ).to_csv(samples, sep="\t", index=False)

    _write(
        results / "rna_type" / "SAMN1.json",
        _rna("SAMN1", "ribo_depleted_total_rna", True),
    )
    _write(results / "rna_type" / "SAMN2.json", _rna("SAMN2", "total_rna", False))
    # SAMN3 is classified eligible but its label stage has not completed.
    _write(results / "rna_type" / "SAMN3.json", _rna("SAMN3", "mrna", True))

    for samn in ("SAMN1", "SAMN2"):
        _write(
            results / "tissue" / f"{samn}.json",
            {"biosample": samn, "tissue": "leaf", "source": "rules"},
        )
        _write(
            results / "germplasm" / f"{samn}.json",
            {
                "biosample": samn,
                "germplasm_type": "natural_accession",
                "is_natural_accession": True,
                "source": "rules",
            },
        )
        _write(
            results / "exposure" / f"{samn}.json",
            {"biosample": samn, "terms": [], "other": False},
        )
        _write(
            results / "study_condition" / f"{samn}.json",
            {"biosample": samn, "term_id": None, "label": "OTHER", "other": True},
        )
    for run, gsm, tissue, genotype in (
        ("SRR1", "GSM9001", "leaf", "wild type"),
        ("SRR2", None, None, None),
    ):
        _write(
            results / "metadata" / "athrdb" / f"{run}.json",
            {
                "run": run,
                "gsm": gsm,
                "athrdb_hit": bool(gsm),
                "athrdb_tissue": tissue,
                "athrdb_genotype": genotype,
                "athrdb_ecotype": "Col-0" if gsm else None,
            },
        )

    _write(
        results / "summary" / "PRJNA1.json",
        {
            "has_paper": True,
            "low_confidence": False,
            "conditions": {
                "day_length_hours": 16,
                "growth_temperature_c": 22,
            },
        },
    )
    index = tmp_path / "index"
    _write(index / "terms.json", [])

    labels_path = results / "labels.tsv"
    excluded_path = results / "labels.excluded.tsv"
    sheet = pd.read_table(samples, dtype=str)
    aggregate.build_rows(
        sheet,
        list(sheet["biosample"]),
        REVIEW,
        {},
        window="0",
        destination=results / "rows" / "0-0.tsv",
    )
    monkeypatch.setattr(
        aggregate,
        "snakemake",
        SimpleNamespace(
            output=SimpleNamespace(
                labels=str(labels_path), excluded=str(excluded_path)
            ),
            params=SimpleNamespace(samples=str(samples)),
        ),
        raising=False,
    )
    aggregate.main()

    labels = pd.read_csv(labels_path, sep="\t", keep_default_na=False)
    excluded = pd.read_csv(excluded_path, sep="\t", keep_default_na=False)
    assert labels["run"].tolist() == ["SRR1"]
    assert labels["rna_type"].tolist() == ["ribo_depleted_total_rna"]
    assert labels["mrna_eligible"].tolist() == [True]
    assert labels["paper_day_length_hours"].tolist() == [16]
    assert labels["paper_growth_temperature_c"].tolist() == [22]
    assert labels["athrdb_gsm"].tolist() == ["GSM9001"]
    assert labels["athrdb_tissue"].tolist() == ["leaf"]
    assert labels["athrdb_genotype"].tolist() == ["wild type"]
    assert excluded["run"].tolist() == ["SRR2"]
    assert excluded["exclusion_reason"].tolist() == ["rna_type_total_rna_not_accepted"]


def test_aggregate_ignores_incomplete_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = tmp_path / "results"
    samples = tmp_path / "samples.tsv"
    pd.DataFrame(
        [
            {
                "run": "SRR4",
                "biosample": "SAMN4",
                "bioproject": "PRJNA2",
                "species": "Arabidopsis thaliana",
            }
        ]
    ).to_csv(samples, sep="\t", index=False)

    _write(results / "rna_type" / "SAMN4.json", _rna("SAMN4", "mrna", True))
    # No tissue/germplasm/exposure/study/athrdb yet: the window is incomplete.

    index = tmp_path / "index"
    _write(index / "terms.json", [])
    labels_path = results / "labels.tsv"
    excluded_path = results / "labels.excluded.tsv"
    sheet = pd.read_table(samples, dtype=str)
    aggregate.build_rows(
        sheet,
        list(sheet["biosample"]),
        REVIEW,
        {},
        window="0",
        destination=results / "rows" / "0-0.tsv",
    )
    monkeypatch.setattr(
        aggregate,
        "snakemake",
        SimpleNamespace(
            output=SimpleNamespace(
                labels=str(labels_path), excluded=str(excluded_path)
            ),
            params=SimpleNamespace(samples=str(samples)),
        ),
        raising=False,
    )
    aggregate.main()

    labels = pd.read_csv(labels_path, sep="\t", keep_default_na=False)
    excluded = pd.read_csv(excluded_path, sep="\t", keep_default_na=False)
    assert labels.empty
    assert excluded.empty
