"""Tests for loading workflow artifacts."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from review_app import loaders


def test_paper_url_prefers_pmcid():
    assert (
        loaders.paper_url({"pmcid": "PMC123", "pmid": "456"})
        == "https://europepmc.org/article/PMC/PMC123"
    )
    assert loaders.paper_url({"pmid": "456"}) == "https://pubmed.ncbi.nlm.nih.gov/456/"
    assert loaders.paper_url(None) is None
    assert loaders.paper_url({"status": "none"}) is None


def test_load_json_missing(tmp_path):
    assert loaders.load_json(tmp_path / "missing.json") is None


def test_load_labels_rejects_duplicates_and_missing_columns(tmp_path):
    path = tmp_path / "labels.tsv"
    pd.DataFrame(
        [
            {
                "run": "SRR1",
                "biosample": "SAMN1",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
                "review_required": "True",
                "review_reasons": "",
            },
            {
                "run": "SRR1",
                "biosample": "SAMN2",
                "bioproject": "PRJNA1",
                "species": "Arabidopsis thaliana",
                "review_required": "True",
                "review_reasons": "",
            },
        ]
    ).to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="duplicate"):
        loaders.load_labels(path)

    pd.DataFrame([{"run": "SRR1"}]).to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="missing columns"):
        loaders.load_labels(path)


def test_load_terms_requires_list(tmp_path):
    index = tmp_path / "peco_index"
    index.mkdir()
    (index / "terms.json").write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError, match="list"):
        loaders.load_terms(index)
    with pytest.raises(FileNotFoundError):
        loaders.load_terms(tmp_path / "missing")


def test_branch_terms_and_run_bundle(tmp_path):
    terms = [
        {"id": "PECO:1", "branch": "exposure"},
        {"id": "PECO:2", "branch": "study_condition"},
        {"id": "PECO:3", "branch": "other"},
    ]
    assert loaders.branch_terms(terms, "exposure") == [terms[0]]
    bundle = loaders.load_run_bundle(
        tmp_path,
        {
            "run": "SRR1",
            "biosample": "SAMN1",
            "bioproject": "PRJNA1",
        },
    )
    assert all(value == {} for value in bundle.values())
