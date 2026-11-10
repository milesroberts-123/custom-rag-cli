"""Tests for exposure-response validation and contradiction resolution.

The model occasionally returns ``other`` alongside grounded terms, or together
with ``no_condition``. Those responses used to fail the sample; they are now
resolved deterministically so a contradiction costs a review note, not a label.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from exposure_validation import validate_exposure_response

TERMS = {
    "PECO:0007032": {"label": "control exposure"},
    "PECO:0007315": {"label": "drought exposure"},
}
CANDIDATES = set(TERMS)


def _response(terms, **flags):
    return {
        "terms": [{"term_id": tid, "evidence": "BioSample: drought"} for tid in terms],
        **flags,
    }


def test_terms_without_flags_pass_through():
    terms, no_condition, other, suggested, conflicts = validate_exposure_response(
        _response(["PECO:0007315"], other=False, no_condition=False),
        CANDIDATES,
        TERMS,
    )
    assert [term["term_id"] for term in terms] == ["PECO:0007315"]
    assert (no_condition, other, suggested, conflicts) == (False, False, "", [])


def test_other_with_terms_keeps_the_grounded_terms():
    terms, no_condition, other, suggested, conflicts = validate_exposure_response(
        _response(
            ["PECO:0007315"], other=True, no_condition=False, suggested_label="heat"
        ),
        CANDIDATES,
        TERMS,
    )
    assert [term["term_id"] for term in terms] == ["PECO:0007315"]
    assert other is False
    assert suggested == ""
    assert conflicts == ["other_with_terms"]


def test_no_condition_with_terms_keeps_the_terms():
    terms, no_condition, other, _, conflicts = validate_exposure_response(
        _response(["PECO:0007032"], other=False, no_condition=True),
        CANDIDATES,
        TERMS,
    )
    assert len(terms) == 1
    assert no_condition is False
    assert conflicts == ["no_condition_with_terms"]


def test_other_and_no_condition_without_terms_prefers_other():
    terms, no_condition, other, suggested, conflicts = validate_exposure_response(
        _response([], other=True, no_condition=True, suggested_label="cold"),
        CANDIDATES,
        TERMS,
    )
    assert terms == []
    assert no_condition is False
    assert other is True
    assert suggested == "cold"
    assert conflicts == ["other_and_no_condition"]


def test_empty_response_is_still_rejected():
    with pytest.raises(ValueError, match="empty terms list"):
        validate_exposure_response({"terms": []}, CANDIDATES, TERMS)


def test_unknown_term_id_is_still_rejected():
    with pytest.raises(ValueError, match="not in the candidate list"):
        validate_exposure_response(_response(["PECO:9999999"]), CANDIDATES, TERMS)


def test_term_without_evidence_is_still_rejected():
    parsed = {"terms": [{"term_id": "PECO:0007315", "evidence": "  "}]}
    with pytest.raises(ValueError, match="has no evidence"):
        validate_exposure_response(parsed, CANDIDATES, TERMS)
