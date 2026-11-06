"""Tests for the fragment-based aggregation model.

Row building happens per window-chunk (`sample_rows`), and `aggregate` only
concatenates fragments, so window cost is proportional to the samples labeled
rather than to every run on the sheet.
"""

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


def _sample_sheet(path):
    pd.DataFrame(
        [
            {
                "run": "SRR1",
                "biosample": "SAMN1",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
            }
        ]
    ).to_csv(path, sep="\t", index=False)


def _labels(root, tissue="leaf", eligible=True):
    _write(
        root / "results" / "rna_type" / "SAMN1.json",
        {
            "biosample": "SAMN1",
            "rna_type": "mrna" if eligible else "total_rna",
            "mrna_eligible": eligible,
            "source": "rules",
            "confidence": 0.9,
        },
    )
    for kind, payload in (
        ("tissue", {"tissue": tissue, "source": "rules"}),
        ("germplasm", {"germplasm_type": "natural_accession", "source": "rules"}),
        ("exposure", {"terms": [], "other": False}),
        ("study_condition", {"term_id": None, "label": "OTHER"}),
    ):
        _write(
            root / "results" / kind / "SAMN1.json", {"biosample": "SAMN1", **payload}
        )
    _write(
        root / "results" / "summary" / "PRJNA1.json",
        {"has_paper": False, "low_confidence": True, "conditions": {}},
    )


def _aggregate(root, monkeypatch, sheet):
    labels = root / "results" / "labels.tsv"
    excluded = root / "results" / "labels.excluded.tsv"
    monkeypatch.setattr(
        aggregate,
        "snakemake",
        SimpleNamespace(
            output=SimpleNamespace(labels=str(labels), excluded=str(excluded)),
            params=SimpleNamespace(samples=str(sheet)),
        ),
        raising=False,
    )
    aggregate.main()
    return (
        pd.read_csv(labels, sep="\t", keep_default_na=False),
        pd.read_csv(excluded, sep="\t", keep_default_na=False),
    )


def test_fragment_rows_are_written_per_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sheet = tmp_path / "samples.tsv"
    _sample_sheet(sheet)
    _labels(tmp_path)

    frame = pd.read_table(sheet, dtype=str)
    written = aggregate.build_rows(
        frame, ["SAMN1"], REVIEW, {}, window="0", destination="results/rows/0-0.tsv"
    )

    fragment = pd.read_csv(
        tmp_path / "results/rows/0-0.tsv", sep="\t", dtype=str, keep_default_na=False
    )
    assert written == 1
    assert fragment["included"].tolist() == ["True"]
    assert fragment["tissue"].tolist() == ["leaf"]


def test_newer_window_fragment_wins_for_the_same_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sheet = tmp_path / "samples.tsv"
    _sample_sheet(sheet)
    _labels(tmp_path, tissue="leaf")
    frame = pd.read_table(sheet, dtype=str)
    aggregate.build_rows(
        frame, ["SAMN1"], REVIEW, {}, window="1", destination="results/rows/1-0.tsv"
    )

    _labels(tmp_path, tissue="root")
    aggregate.build_rows(
        frame, ["SAMN1"], REVIEW, {}, window="2", destination="results/rows/2-0.tsv"
    )

    labels, excluded = _aggregate(tmp_path, monkeypatch, sheet)
    assert labels["run"].tolist() == ["SRR1"]
    assert labels["tissue"].tolist() == ["root"]
    assert excluded.empty


def test_non_eligible_run_goes_to_excluded_fragment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sheet = tmp_path / "samples.tsv"
    _sample_sheet(sheet)
    _labels(tmp_path, eligible=False)
    frame = pd.read_table(sheet, dtype=str)
    aggregate.build_rows(
        frame, ["SAMN1"], REVIEW, {}, window="0", destination="results/rows/0-0.tsv"
    )

    labels, excluded = _aggregate(tmp_path, monkeypatch, sheet)
    assert labels.empty
    assert excluded["run"].tolist() == ["SRR1"]
    assert excluded["exclusion_reason"].tolist() == ["rna_type_total_rna_not_accepted"]


def test_aggregate_never_reads_per_run_metadata(tmp_path, monkeypatch):
    """Only fragments matter: no label JSONs exist, rows still aggregate."""
    monkeypatch.chdir(tmp_path)
    sheet = tmp_path / "samples.tsv"
    _sample_sheet(sheet)
    rows = tmp_path / "results" / "rows" / "0-0.tsv"
    rows.parent.mkdir(parents=True)
    rows.write_text(
        "run\tbiosample\tbioproject\tspecies\ttissue\tincluded\n"
        "SRR1\tSAMN1\tPRJNA1\tA. thaliana\tleaf\tTrue\n"
    )

    labels, excluded = _aggregate(tmp_path, monkeypatch, sheet)
    assert labels["tissue"].tolist() == ["leaf"]
    assert excluded.empty
