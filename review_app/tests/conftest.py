"""Shared fixtures for review app tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from review_app import db


@pytest.fixture
def base_rows():
    return [
        {
            "run": "SRR000001",
            "biosample": "SAMN000001",
            "bioproject": "PRJNA000001",
            "species": "Arabidopsis thaliana",
            "tissue": "leaf",
            "tissue_source": "rules",
            "tissue_confidence": "0.91",
            "germplasm_type": "natural_accession",
            "is_natural_accession": "True",
            "germplasm_confidence": "0.88",
            "germplasm_evidence": "Col-0",
            "peco_exposure_ids": "PECO:0000001;PECO:0000002",
            "peco_exposure_labels": "cold exposure;agar medium",
            "peco_exposure_evidence": "cold; agar",
            "peco_exposure_other": "False",
            "peco_exposure_max_score": "0.80",
            "peco_study_id": "PECO:0000003",
            "peco_study_label": "growth chamber study",
            "peco_study_confidence": "0.77",
            "growth_system_ids": "PECO:0000002",
            "growth_system_labels": "agar medium",
            "has_paper": "True",
            "paper_low_confidence": "False",
            "review_required": "True",
            "review_reasons": "tissue_other",
        },
        {
            "run": "SRR000002",
            "biosample": "SAMN000002",
            "bioproject": "PRJNA000001",
            "species": "Arabidopsis thaliana",
            "tissue": "root",
            "tissue_source": "decision",
            "tissue_confidence": "0.72",
            "germplasm_type": "mutant",
            "is_natural_accession": "False",
            "germplasm_confidence": "0.66",
            "germplasm_evidence": "SALK line",
            "peco_exposure_ids": "PECO:0000001",
            "peco_exposure_labels": "cold exposure",
            "peco_exposure_evidence": "cold",
            "peco_exposure_other": "False",
            "peco_exposure_max_score": "0.62",
            "peco_study_id": "PECO:0000003",
            "peco_study_label": "growth chamber study",
            "peco_study_confidence": "0.70",
            "growth_system_ids": "",
            "growth_system_labels": "",
            "has_paper": "True",
            "paper_low_confidence": "False",
            "review_required": "True",
            "review_reasons": "germplasm_low_confidence",
        },
        {
            "run": "SRR000003",
            "biosample": "SAMN000003",
            "bioproject": "PRJNA000002",
            "species": "Arabidopsis thaliana",
            "tissue": "seed",
            "tissue_source": "rules",
            "tissue_confidence": "0.95",
            "germplasm_type": "natural_accession",
            "is_natural_accession": "True",
            "germplasm_confidence": "0.90",
            "germplasm_evidence": "Ler-0",
            "peco_exposure_ids": "",
            "peco_exposure_labels": "",
            "peco_exposure_evidence": "",
            "peco_exposure_other": "False",
            "peco_exposure_max_score": "",
            "peco_study_id": "PECO:0000004",
            "peco_study_label": "field study",
            "peco_study_confidence": "0.81",
            "growth_system_ids": "",
            "growth_system_labels": "",
            "has_paper": "False",
            "paper_low_confidence": "True",
            "review_required": "False",
            "review_reasons": "",
        },
    ]


@pytest.fixture
def terms():
    return [
        {
            "id": "PECO:0000001",
            "label": "cold exposure",
            "definition": "Exposure to low temperature.",
            "synonyms": ["cold stress"],
            "branch": "exposure",
            "growth_system": False,
            "parents": [],
        },
        {
            "id": "PECO:0000002",
            "label": "agar medium",
            "definition": "Growth on agar medium.",
            "synonyms": ["agar plate"],
            "branch": "exposure",
            "growth_system": True,
            "parents": [],
        },
        {
            "id": "PECO:0000003",
            "label": "growth chamber study",
            "definition": "Plants grown in a growth chamber.",
            "synonyms": [],
            "branch": "study_condition",
            "growth_system": False,
            "parents": [],
        },
        {
            "id": "PECO:0000004",
            "label": "field study",
            "definition": "Plants grown in the field.",
            "synonyms": [],
            "branch": "study_condition",
            "growth_system": False,
            "parents": [],
        },
    ]


@pytest.fixture
def review_db(tmp_path):
    connection = db.connect(tmp_path / "review.db")
    yield connection
    connection.close()


@pytest.fixture
def review_root(tmp_path, base_rows, terms):
    root = tmp_path / "root"
    labels = root / "results" / "labels.tsv"
    labels.parent.mkdir(parents=True)
    columns = list(base_rows[0].keys())
    lines = ["\t".join(columns)]
    for row in base_rows:
        lines.append("\t".join(str(row[column]) for column in columns))
    labels.write_text("\n".join(lines) + "\n")

    index = root / "resources" / "peco_index"
    index.mkdir(parents=True)
    (index / "terms.json").write_text(json.dumps(terms))

    config = root / "config"
    config.mkdir(parents=True)
    (config / "config.yaml").write_text(
        """
tissue:
  categories:
    - leaf
    - root
    - seed
germplasm:
  categories:
    - natural_accession
    - mutant
    - unknown
"""
    )
    return root
