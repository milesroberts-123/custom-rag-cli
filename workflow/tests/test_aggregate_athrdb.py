"""Tests for the AthRDB-vs-label cross-check in aggregate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate


def _tissue(value):
    return {"tissue": value, "source": "decision", "confidence": 0.9}


def _germplasm(value):
    return {"germplasm_type": value, "confidence": 0.9}


def _review():
    return {
        "tissue_confidence": 0.6,
        "germplasm_confidence": 0.6,
        "exposure_retrieval_score": 0.55,
        "study_confidence": 0.6,
        "rna_type_confidence": 0.6,
        "flag_missing_paper": True,
        "flag_low_confidence_paper": True,
        "athrdb_crosscheck": True,
    }


def _reasons(athrdb, tissue=None, germplasm=None, review=None):
    return aggregate._review_reasons(
        tissue or _tissue("leaf"),
        germplasm or _germplasm("natural_accession"),
        {"terms": [], "other": False},
        {"label": "in vitro"},
        {"has_paper": True},
        {"confidence": 0.9},
        athrdb,
        review or _review(),
    )


def test_no_athrdb_record_means_no_flag():
    assert "athrdb_disagreement" not in _reasons({"athrdb_hit": False})


def test_tissue_mismatch_flags_review():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "root",
        "athrdb_genotype": "wild type",
    }
    reasons = _reasons(athrdb, tissue=_tissue("leaf"))
    assert "athrdb_disagreement" in reasons


def test_matching_tissue_does_not_flag():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "leaf",
        "athrdb_genotype": "wild type",
    }
    reasons = _reasons(athrdb, tissue=_tissue("leaf"))
    assert "athrdb_disagreement" not in reasons


def test_mutant_genotype_vs_natural_label_flags_review():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "leaf",
        "athrdb_genotype": "ros1 dml2 dml3",
    }
    reasons = _reasons(athrdb, germplasm=_germplasm("natural_accession"))
    assert "athrdb_disagreement" in reasons


def test_wild_genotype_vs_mutant_label_flags_review():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "leaf",
        "athrdb_genotype": "wild type",
    }
    reasons = _reasons(athrdb, germplasm=_germplasm("mutant"))
    assert "athrdb_disagreement" in reasons


def test_agreeing_genotype_does_not_flag():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "leaf",
        "athrdb_genotype": "wild type",
    }
    reasons = _reasons(athrdb, germplasm=_germplasm("natural_accession"))
    assert "athrdb_disagreement" not in reasons


def test_unknown_model_germplasm_never_flags():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "leaf",
        "athrdb_genotype": "ros1 dml2 dml3",
    }
    reasons = _reasons(athrdb, germplasm=_germplasm("unknown"))
    assert "athrdb_disagreement" not in reasons


def test_crosscheck_can_be_disabled():
    athrdb = {
        "athrdb_hit": True,
        "athrdb_tissue": "root",
        "athrdb_genotype": "wild type",
    }
    review = _review()
    review["athrdb_crosscheck"] = False
    reasons = _reasons(athrdb, tissue=_tissue("leaf"), review=review)
    assert "athrdb_disagreement" not in reasons
