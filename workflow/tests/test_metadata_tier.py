"""Metadata provenance: which evidence families a sample's record provides.

Label quality statistics are dominated by submissions that carry nothing but
ENA boilerplate, so `labels.tsv` records a tier and the missing families. These
tests pin the classification rules.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate

KEYS = {
    "tissue": ["tissue", "organism part", "plant structure"],
    "germplasm": ["genotype", "ecotype", "cultivar", "strain"],
    "growth_condition": ["isolation and growth condition", "growth condition"],
}

BOILERPLATE = {
    "ENA-CHECKLIST": "ERC000011",
    "common name": "thale cress",
    "organism": "Arabidopsis thaliana",
    "scientific_name": "Arabidopsis thaliana",
}


def _state(attributes, has_paper=False):
    return aggregate.metadata_state(attributes, has_paper, KEYS)


def test_boilerplate_only_record_is_empty():
    tier, missing, n = _state(BOILERPLATE)
    assert tier == "empty"
    assert n == 0
    assert missing == "tissue;germplasm;growth_condition;paper"


def test_one_family_is_partial():
    attributes = {**BOILERPLATE, "organism part": "leaf"}
    tier, missing, n = _state(attributes)
    assert tier == "partial"
    assert n == 1
    assert missing == "germplasm;growth_condition;paper"


def test_two_families_are_annotated():
    attributes = {**BOILERPLATE, "organism part": "leaf", "genotype": "Col-0"}
    tier, missing, n = _state(attributes)
    assert tier == "annotated"
    assert n == 2
    assert missing == "growth_condition;paper"


def test_placeholder_values_do_not_count_as_evidence():
    attributes = {
        **BOILERPLATE,
        "organism part": "not applicable",
        "genotype": "NA",
        "isolation and growth condition": "",
    }
    tier, missing, _ = _state(attributes)
    assert tier == "empty"
    assert missing == "tissue;germplasm;growth_condition;paper"


def test_paper_only_counts_for_missing_but_not_for_the_tier():
    tier, missing, n = _state(BOILERPLATE, has_paper=True)
    assert tier == "empty"
    assert n == 0
    assert missing == "tissue;germplasm;growth_condition"


def test_non_family_attributes_count_toward_informative_total():
    attributes = {**BOILERPLATE, "collection date": "2022-02-02", "age": "12"}
    tier, missing, n = _state(attributes)
    assert tier == "partial"
    assert n == 2
    assert missing == "tissue;germplasm;growth_condition;paper"


def test_coverage_table_reports_per_project_tiers():
    included = pd.DataFrame(
        [
            {
                "run": "SRR1",
                "biosample": "SAMN1",
                "bioproject": "PRJNA1",
                "metadata_tier": "empty",
                "tissue": "OTHER",
                "germplasm_type": "unknown",
                "peco_study_label": "OTHER",
                "has_paper": "False",
            },
            {
                "run": "SRR2",
                "biosample": "SAMN2",
                "bioproject": "PRJNA1",
                "metadata_tier": "annotated",
                "tissue": "leaf",
                "germplasm_type": "natural_accession",
                "peco_study_label": "field study",
                "has_paper": "True",
            },
        ]
    )
    table = aggregate.coverage_table(included, pd.DataFrame())
    row = table.iloc[0]
    assert row["bioproject"] == "PRJNA1"
    assert row["samples"] == 2
    assert row["tier_empty"] == 1 and row["tier_annotated"] == 1
    assert row["tissue_other_pct"] == 50.0
    assert row["has_paper_pct"] == 50.0


def test_fragment_rows_carry_metadata_columns(tmp_path, monkeypatch):
    """sample_rows passes BioSample attributes through to the fragment."""
    import json

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

    written = aggregate.build_rows(
        pd.read_table(sheet, dtype=str),
        ["SAMN1"],
        {"tissue_confidence": 0.5, "germplasm_confidence": 0.5},
        {},
        window="0",
        destination="results/rows/0-0.tsv",
        attributes={
            "SAMN1": {
                "ENA-CHECKLIST": "ERC000011",
                "organism": "Arabidopsis thaliana",
                "organism part": "leaf",
                "genotype": "Col-0",
            }
        },
        metadata_keys=KEYS,
    )

    fragment = pd.read_csv(
        tmp_path / "results/rows/0-0.tsv", sep="\t", dtype=str, keep_default_na=False
    )
    assert written == 1
    assert fragment["metadata_tier"].tolist() == ["annotated"]
    assert fragment["metadata_missing"].tolist() == ["growth_condition;paper"]
    assert fragment["n_informative_attributes"].tolist() == ["2"]
