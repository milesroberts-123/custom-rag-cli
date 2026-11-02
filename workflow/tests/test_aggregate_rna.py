"""Tests for RNA-type filtering in the aggregate rule."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_aggregate_filters_non_eligible_runs(tmp_path, monkeypatch):
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
        ]
    ).to_csv(samples, sep="\t", index=False)

    rna_paths = []
    for run, rna_type, eligible in (
        ("SRR1", "ribo_depleted_total_rna", True),
        ("SRR2", "total_rna", False),
    ):
        path = results / "rna_type" / f"{run}.json"
        _write(
            path,
            {
                "run": run,
                "rna_type": rna_type,
                "rna_subtype": None,
                "ribo_depleted": rna_type == "ribo_depleted_total_rna",
                "mrna_eligible": eligible,
                "confidence": 1.0,
                "source": "rules",
                "evidence": "test",
            },
        )
        rna_paths.append(str(path))
        _write(
            results / "tissue" / f"{run}.json",
            {"run": run, "tissue": "leaf", "source": "rules"},
        )
        _write(
            results / "germplasm" / f"{run}.json",
            {
                "run": run,
                "germplasm_type": "natural_accession",
                "is_natural_accession": True,
                "source": "rules",
            },
        )
        _write(
            results / "exposure" / f"{run}.json",
            {"run": run, "terms": [], "other": False},
        )
        _write(
            results / "study_condition" / f"{run}.json",
            {"run": run, "term_id": None, "label": "OTHER", "other": True},
        )

    _write(
        results / "summary" / "PRJNA1.json",
        {"has_paper": False, "low_confidence": True},
    )
    index = tmp_path / "index"
    _write(index / "terms.json", [])

    labels_path = results / "labels.tsv"
    excluded_path = results / "labels.excluded.tsv"
    monkeypatch.setattr(
        aggregate,
        "snakemake",
        SimpleNamespace(
            input=SimpleNamespace(
                rna_type=rna_paths,
                tissue=[str(results / "tissue" / f"SRR{i}.json") for i in (1, 2)],
                germplasm=[str(results / "germplasm" / f"SRR{i}.json") for i in (1, 2)],
                exposure=[str(results / "exposure" / f"SRR{i}.json") for i in (1, 2)],
                study=[
                    str(results / "study_condition" / f"SRR{i}.json") for i in (1, 2)
                ],
                index=str(index),
            ),
            output=SimpleNamespace(
                labels=str(labels_path), excluded=str(excluded_path)
            ),
            params=SimpleNamespace(
                samples=str(samples),
                review={
                    "rna_type_confidence": 0.6,
                    "tissue_confidence": 0.6,
                    "germplasm_confidence": 0.6,
                    "exposure_retrieval_score": 0.55,
                    "study_confidence": 0.6,
                    "flag_missing_paper": True,
                    "flag_low_confidence_paper": True,
                },
            ),
        ),
        raising=False,
    )
    aggregate.main()

    labels = pd.read_csv(labels_path, sep="\t", keep_default_na=False)
    excluded = pd.read_csv(excluded_path, sep="\t", keep_default_na=False)
    assert labels["run"].tolist() == ["SRR1"]
    assert labels["rna_type"].tolist() == ["ribo_depleted_total_rna"]
    assert labels["mrna_eligible"].tolist() == [True]
    assert excluded["run"].tolist() == ["SRR2"]
    assert excluded["exclusion_reason"].tolist() == ["rna_type_total_rna_not_accepted"]
