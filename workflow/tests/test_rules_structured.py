"""Tests for the structured-field restrictions in the tissue/germplasm rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import label_germplasm as germ
import label_tissue as tissue

import llm
from peco_utils import ancestor_map, prune_ancestors

TISSUE_CATEGORIES = ["leaf", "root", "shoot"]
TISSUE_KEYWORDS = {
    "leaf": ["leaf", "leaves", "rosette"],
    "root": ["root", "roots"],
    "shoot": ["shoot", "stem"],
}
TISSUE_PO = {"PO:0025034": "leaf", "PO:0009005": "root", "PO:0009047": "shoot"}
TISSUE_RULE_KEYS = [
    "tissue",
    "organism part",
    "organ",
    "tissue type",
    "sample tissue",
    "cell type",
    "plant structure",
    "plant anatomy",
]

GERM_PATTERNS = {
    "mutant": [r"\bmutant\b", r"\bknockout\b"],
    "transgenic": [r"\b35S\b", r"\bpUBQ\w*"],
}
GERM_ACCESSIONS = ["Col-0", "Columbia"]
GERM_RULE_KEYS = [
    "genotype",
    "ecotype",
    "cultivar",
    "strain",
]


# --- tissue ---


def test_tissue_po_id_resolves():
    values = ["sra_plant structure: PO:0025034"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        == "leaf"
    )


def test_tissue_keyword_in_free_text_abstains():
    values = ["study_title: green leaf volatiles regulate defence"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        is None
    )


def test_tissue_plural_keyword_in_structured_line():
    values = ["organism part: leaves"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        == "leaf"
    )


def test_tissue_rosette_synonym_in_structured_line():
    values = ["tissue: rosette"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        == "leaf"
    )


def test_tissue_multi_category_abstains():
    values = ["sra_plant structure: PO:0025034;PO:0009005"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        is None
    )


def test_tissue_only_free_text_abstains():
    values = ["study_abstract: roots were sampled", "sra_Submitter Id: ena-x-1"]
    assert (
        tissue._rules_category(
            values, TISSUE_CATEGORIES, TISSUE_KEYWORDS, TISSUE_PO, TISSUE_RULE_KEYS
        )
        is None
    )


# --- germplasm ---


def test_germplasm_transgene_in_library_name_abstains_to_model():
    # Library names carry transgene signals, but the rules layer must not
    # read them: window 2's false transgenic calls came from title/library
    # matching. The model sees these lines and decides.
    values = [
        "sra_Submitter Id: ena-SAMPLE-TAB-24-11-2022",
        "library_name: T3-pUBQ-MORC1-FLAG-mail1-1-rep3",
    ]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category is None


def test_germplasm_t_dna_in_genotype_is_mutant():
    # T-DNA insertion lines are knockouts (mutants), not transgenics.
    values = ["sra_genotype: SALK_123456 (T-DNA insertion)", "ecotype: Col-0"]
    patterns = {
        "mutant": [r"\bSALK_\d+", r"\bT-DNA\b"],
        "transgenic": [r"\b35S\b"],
    }
    category, evidence, _ = germ._rule_label(
        values, GERM_ACCESSIONS, patterns, GERM_RULE_KEYS
    )
    assert category == "mutant"
    assert "SALK_123456" in evidence


def test_germplasm_evidence_quotes_matching_lines_only():
    # Evidence must cite the lines that matched, not unrelated structured
    # lines: the old version quoted the first three structured lines for
    # every hit, which cited T-DNA evidence that appeared nowhere.
    values = [
        "sra_genotype: wild type Col-0",
        "sra_genotype: atg5-1 knockout",
    ]
    patterns = {"mutant": [r"\bknockout\b"]}
    category, evidence, _ = germ._rule_label(
        values, GERM_ACCESSIONS, patterns, GERM_RULE_KEYS
    )
    assert category == "mutant"
    assert "atg5-1 knockout" in evidence
    assert "wild type" not in evidence


def test_germplasm_pattern_only_in_abstract_abstains():
    values = ["study_abstract: a knockout mutant was used"]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category is None


def test_germplasm_natural_from_genotype_line():
    values = ["sra_genotype: Col-0"]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category == "natural_accession"


def test_germplasm_only_free_text_abstains():
    values = ["study_title: F1 hybrid analysis", "sra_sample name: SRX1"]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category is None


# --- exposure ancestor pruning ---


def test_exposure_prune_drops_ancestor_of_selected():
    terms = [
        {"id": "PECO:1", "parents": []},
        {"id": "PECO:2", "parents": ["PECO:1"]},
        {"id": "PECO:3", "parents": ["PECO:1"]},
    ]
    ancestors = ancestor_map(terms)
    selected = [{"term_id": "PECO:1"}, {"term_id": "PECO:2"}]
    kept, dropped = prune_ancestors(selected, ancestors)
    assert [term["term_id"] for term in kept] == ["PECO:2"]
    assert dropped == ["PECO:1"]


def test_exposure_prune_keeps_unrelated_terms():
    terms = [
        {"id": "PECO:1", "parents": []},
        {"id": "PECO:2", "parents": ["PECO:1"]},
        {"id": "PECO:3", "parents": []},
    ]
    ancestors = ancestor_map(terms)
    selected = [{"term_id": "PECO:2"}, {"term_id": "PECO:3"}]
    kept, dropped = prune_ancestors(selected, ancestors)
    assert sorted(term["term_id"] for term in kept) == ["PECO:2", "PECO:3"]
    assert dropped == []


# --- decision-model availability ---


class _FakeResponse:
    status_code = 404

    def json(self):
        return {"error": "model 'tev1:4b' not found"}

    @property
    def text(self):
        return ""


def test_systemone_404_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: _FakeResponse())
    try:
        llm.systemone("http://node:11434", "k", "tev1:4b", {}, {})
    except RuntimeError as error:
        assert "pull tev1:4b" in str(error)
        assert "/v1/systemone" in str(error)
    else:
        raise AssertionError("expected RuntimeError for a missing decision model")
