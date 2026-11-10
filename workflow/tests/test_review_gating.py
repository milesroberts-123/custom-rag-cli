"""Review gating: only model uncertainty sends a sample to a human.

``OTHER``/``unknown`` outcomes are labeling results. Flagging them enqueued 94%
of one window, so these tests pin the rule that confidence (and the AthRDB
cross-check) decide review, never the label value itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import aggregate

REVIEW = {
    "rna_type_confidence": 0.5,
    "tissue_confidence": 0.5,
    "germplasm_confidence": 0.5,
    "exposure_retrieval_score": 0.55,
    "study_confidence": 0.5,
    "athrdb_crosscheck": False,
}


def _reasons(tissue, germplasm, exposure, study, rna_type=None):
    return aggregate._review_reasons(
        tissue,
        germplasm,
        exposure,
        study,
        rna_type or {"confidence": 0.95},
        {},
        REVIEW,
    )


def test_confident_other_labels_are_not_flagged():
    reasons = _reasons(
        {"tissue": "OTHER", "source": "decision", "confidence": 0.92},
        {"germplasm_type": "unknown", "source": "decision", "confidence": 0.9},
        {"terms": [], "other": True, "max_retrieval_score": 0.9},
        {"label": "OTHER", "other": True, "confidence": 0.9},
    )
    assert reasons == []


def test_missing_attributes_alone_is_not_flagged():
    reasons = _reasons(
        {"tissue": "OTHER", "source": "missing_attributes"},
        {"germplasm_type": "unknown", "source": "rules", "confidence": 1.0},
        {"terms": [], "other": False, "max_retrieval_score": 0.95},
        {"label": "OTHER", "confidence": 0.95},
    )
    assert reasons == []


def test_low_confidence_labels_are_flagged_per_layer():
    reasons = _reasons(
        {"tissue": "leaf", "source": "decision", "confidence": 0.31},
        {"germplasm_type": "mutant", "confidence": 0.42},
        {"terms": [], "other": False, "max_retrieval_score": 0.2},
        {"label": "field study", "confidence": 0.4},
    )
    assert reasons == [
        "tissue_low_confidence",
        "germplasm_low_confidence",
        "exposure_weak_retrieval",
        "study_low_confidence",
    ]


def test_rules_labels_have_no_confidence_and_are_not_flagged():
    reasons = _reasons(
        {"tissue": "leaf", "source": "rules"},
        {"germplasm_type": "natural_accession", "source": "rules", "confidence": 1.0},
        {"terms": [], "other": False},
        {"label": "OTHER"},
    )
    assert reasons == []


def test_low_confidence_rna_type_is_flagged():
    reasons = aggregate._review_reasons(
        {"tissue": "leaf", "source": "rules"},
        {"germplasm_type": "unknown", "source": "rules"},
        {"terms": [], "other": False},
        {"label": "OTHER", "confidence": 0.9},
        {"rna_type": "mrna", "confidence": 0.2},
        {},
        REVIEW,
    )
    assert reasons == ["rna_type_low_confidence"]


def test_retired_reasons_are_dropped_from_old_fragments():
    """Fragments written before the change must not keep flagging OTHER labels."""
    value = "tissue_other;tissue_low_confidence;study_other;mixed_run_context"
    assert aggregate._retire_reasons(value) == (
        "tissue_low_confidence;mixed_run_context"
    )


def test_retired_reasons_helper_handles_empty_values():
    assert aggregate._retire_reasons("") == ""
    assert aggregate._retire_reasons(None) == ""
