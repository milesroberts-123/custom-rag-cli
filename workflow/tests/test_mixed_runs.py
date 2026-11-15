"""Mixed-run context: computed once per window, not once per chunk.

`sample_rows` used to recompute which BioSamples have inconsistent run context
in every chunk job by re-reading all SRA records of the window (~10 minutes per
job on Lustre). The window-level `mixed_runs` rule now produces it.
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate

KEYS = {
    "tissue": ["organism part"],
    "germplasm": ["genotype"],
    "growth_condition": ["growth condition"],
}


def _sra(tmp_path, run, title, library):
    path = tmp_path / "results/metadata/sra" / f"{run}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"experiment_title": title, "library_name": library}))


def test_samples_with_differing_titles_are_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "title A", "lib1")
    _sra(tmp_path, "SRR2", "title B", "lib2")
    groups = [("SAMN1", ["SRR1", "SRR2"])]
    assert aggregate.mixed_samples(groups) == {"SAMN1"}


def test_identical_context_is_not_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "title A", "lib1")
    _sra(tmp_path, "SRR2", "title A", "lib1")
    groups = [("SAMN1", ["SRR1", "SRR2"])]
    assert aggregate.mixed_samples(groups) == set()


def test_single_run_samples_are_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "title A", "lib1")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1"])]) == set()


def test_missing_sra_records_do_not_break_the_scan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "title A", "lib1")
    # SRR2 has no cached record: it contributes nothing, so nothing disagrees.
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == set()


def test_build_rows_uses_the_precomputed_set(tmp_path, monkeypatch):
    """A precomputed set must short-circuit the per-chunk SRA scan."""
    monkeypatch.chdir(tmp_path)
    sheet = tmp_path / "samples.tsv"
    pd.DataFrame(
        [
            {
                "run": "SRR1",
                "biosample": "SAMN1",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
            }
        ]
    ).to_csv(sheet, sep="\t", index=False)

    root = tmp_path / "results"
    for kind, payload in (
        ("rna_type", {"rna_type": "mrna", "mrna_eligible": True, "source": "rules"}),
        ("tissue", {"tissue": "leaf", "source": "rules"}),
        ("germplasm", {"germplasm_type": "natural_accession", "source": "rules"}),
        ("exposure", {"terms": [], "other": False}),
        ("study_condition", {"term_id": None, "label": "OTHER"}),
    ):
        path = root / kind / "SAMN1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"biosample": "SAMN1", **payload}))
    summary = root / "summary" / "PRJNA1.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps({"has_paper": False, "conditions": {}}))

    def boom(sheet):
        raise AssertionError("build_rows recomputed mixed context")

    monkeypatch.setattr(aggregate, "_mixed_run_samples", boom)

    aggregate.build_rows(
        pd.read_table(sheet, dtype=str),
        ["SAMN1"],
        {"tissue_confidence": 0.5, "germplasm_confidence": 0.5},
        {},
        window="0",
        destination="results/rows/0-0.tsv",
        attributes={"SAMN1": {}},
        metadata_keys=KEYS,
        mixed=["SAMN1"],
    )

    fragment = pd.read_csv(
        tmp_path / "results/rows/0-0.tsv", sep="\t", dtype=str, keep_default_na=False
    )
    assert "mixed_run_context" in fragment["review_reasons"].iloc[0]


# --- normalization ------------------------------------------------------------


def test_lane_and_part_suffixes_are_not_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "RNA-seq of Col-0_Lane1", "")
    _sra(tmp_path, "SRR2", "RNA-seq of Col-0_Lane2", "")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == set()


def test_part_suffixes_are_not_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "Raw reads: ng_py_014_SETI-sag101-ETI", "")
    _sra(tmp_path, "SRR2", "Raw reads: ng_py_014_SETI-sag101-ETI_part2", "")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == set()


def test_replicate_suffixes_are_not_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "ce_rep1", "")
    _sra(tmp_path, "SRR2", "ce_rep2", "")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == set()


def test_library_name_differences_alone_are_not_mixed(tmp_path, monkeypatch):
    # Library names identify the run, so every multi-run sample differs by
    # construction; 654 of 771 flags came from comparing them.
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "NextSeq 500 sequencing", "R1_Col_000")
    _sra(tmp_path, "SRR2", "NextSeq 500 sequencing", "R1_Col_005")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == set()


def test_different_conditions_stay_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _sra(tmp_path, "SRR1", "RNA-seq of Col-0 control", "")
    _sra(tmp_path, "SRR2", "RNA-seq of Col-0 heat stress", "")
    assert aggregate.mixed_samples([("SAMN1", ["SRR1", "SRR2"])]) == {"SAMN1"}


def test_normalize_title_strips_nested_suffixes():
    assert aggregate.normalize_title("Col-0_Lane2") == "col-0"
    assert aggregate.normalize_title("x_part2_rep3") == "x"
    assert aggregate.normalize_title("control") == "control"
    # A time point is a condition, not a run split.
    assert aggregate.normalize_title("Col-0 6h") == "col-0 6h"
