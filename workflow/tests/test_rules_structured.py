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


# --- germplasm: is_hybrid veto -------------------------------------------------
# PRJEB51241 is titled "RNA-seq library of A. thaliana hybrids" and every sample
# was labelled hybrid at confidence 0.63 (above the 0.5 review threshold), but
# its BioSamples record is_hybrid=Inbred for 382 of 576 samples (5,166 runs).

INBRED = ["inbred", "homozygous", "true-breeding"]


def test_inbred_attribute_vetoes_hybrid_label():
    values = [
        "is_hybrid: Inbred",
        "genotype: p6967",
        "organism: Arabidopsis thaliana",
    ]
    category, evidence, source = germ._hybrid_guard(
        "hybrid", values, INBRED, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category == "natural_accession"
    assert source == "rules_override"
    assert "is_hybrid: Inbred" in evidence


def test_hybrid_attribute_keeps_hybrid_label():
    values = ["is_hybrid: Hybrid", "genotype: p6967"]
    category, _, source = germ._hybrid_guard(
        "hybrid", values, INBRED, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category == "hybrid"
    assert source is None


def test_inbred_veto_prefers_a_mutant_signal():
    values = ["is_hybrid: Inbred", "genotype: atg5-1 knockout"]
    category, evidence, source = germ._hybrid_guard(
        "hybrid",
        values,
        INBRED,
        GERM_ACCESSIONS,
        {"mutant": [r"\bknockout\b"]},
        GERM_RULE_KEYS,
    )
    assert category == "mutant"
    assert source == "rules_override"
    assert "knockout" in evidence


def test_guard_leaves_other_labels_alone():
    values = ["is_hybrid: Inbred"]
    category, _, source = germ._hybrid_guard(
        "mutant", values, INBRED, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category == "mutant"
    assert source is None


# --- germplasm: is_hybrid rules layer ----------------------------------------


def _hybrid_rule(values, patterns=None):
    return germ._rule_label(
        values,
        GERM_ACCESSIONS,
        patterns or GERM_PATTERNS,
        GERM_RULE_KEYS,
        ["hybrid"],
        INBRED,
    )


def test_is_hybrid_hybrid_is_decided_by_rules():
    category, evidence, source = _hybrid_rule(["is_hybrid: Hybrid", "genotype: p6967"])
    assert category == "hybrid"
    assert source == "rules"
    assert "is_hybrid: Hybrid" in evidence


def test_is_hybrid_inbred_is_not_hybrid():
    category, evidence, source = _hybrid_rule(["is_hybrid: Inbred", "genotype: p6967"])
    assert category == "natural_accession"
    assert source == "rules"
    assert "is_hybrid: Inbred" in evidence


def test_is_hybrid_inbred_still_yields_a_mutant():
    patterns = {"mutant": [r"\bSALK_\d+", r"\bT-DNA\b"]}
    category, _, _ = _hybrid_rule(
        ["is_hybrid: Inbred", "genotype: SALK_123456 (T-DNA insertion)"], patterns
    )
    assert category == "mutant"


def test_is_hybrid_inbred_defers_when_genotype_says_hybrid():
    # Two structured signals disagree; the model arbitrates with both visible.
    patterns = {"hybrid": [r"\bhybrid\b", r"\bF1\b", r"\bcross\b"]}
    category, _, _ = _hybrid_rule(
        ["is_hybrid: Inbred", "genotype: Col-0 x Ler F1"], patterns
    )
    assert category is None


def test_is_hybrid_ntc_abstains():
    assert _hybrid_rule(["is_hybrid: NTC"])[0] is None


# --- tissue: PO IDs and flower organs discovered in the ENA records ----------
# These were the only two unmapped Plant Ontology IDs in the fetched BioSamples;
# 24 samples fell through to the model and landed in OTHER.

PO_EXTRA = {
    "PO:0000003": "whole_plant",
    "PO:0009006": "shoot",
    "PO:0009047": "shoot",
    "PO:0009005": "root",
    "PO:0025034": "leaf",
    "PO:0000014": "leaf",
    "PO:0009010": "seed",
    "PO:0009046": "flower",
    "PO:0009049": "flower",
    "PO:0009001": "fruit",
}
FLOWER_KEYWORDS = {
    **TISSUE_KEYWORDS,
    "flower": [
        "flower",
        "inflorescence",
        "pollen",
        "ovary",
        "sepal",
        "stamen",
        "anther",
        "petal",
        "carpel",
        "gynoecium",
        "androecium",
        "microspore",
    ],
}


TISSUE_CATEGORIES_WITH_FLOWER = [
    *TISSUE_CATEGORIES,
    "flower",
    "seed",
    "fruit",
    "whole_plant",
]


def _tissue_category(value, keywords=None):
    return tissue._rules_category(
        [value],
        TISSUE_CATEGORIES_WITH_FLOWER,
        keywords or TISSUE_KEYWORDS,
        PO_EXTRA,
        TISSUE_RULE_KEYS,
    )


def test_rosette_leaf_po_id_maps_to_leaf():
    assert _tissue_category("plant structure: PO:0000014") == "leaf"


def test_inflorescence_po_id_maps_to_flower():
    assert _tissue_category("plant structure: PO:0009049") == "flower"


def test_flower_organ_keywords_map_to_flower():
    for value in (
        "organism part: ovary",
        "organism part: sepal",
        "organism part: stamen",
        "organism part: anther",
        "organism part: microspore",
    ):
        assert _tissue_category(value, FLOWER_KEYWORDS) == "flower", value


def test_flower_keywords_do_not_steal_shoot_or_root():
    assert _tissue_category("organism part: stem", FLOWER_KEYWORDS) == "shoot"
    assert _tissue_category("organism part: root", FLOWER_KEYWORDS) == "root"


def test_shipped_config_maps_the_observed_po_ids():
    """Guard the config, not just the helper: these IDs appear in ENA records."""
    import yaml

    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "config.yaml").read_text()
    )
    po_terms = config["tissue"]["po_terms"]
    assert po_terms["PO:0000014"] == "leaf"
    assert po_terms["PO:0009049"] == "flower"
    flower = set(config["tissue"]["keywords"]["flower"])
    for keyword in ("ovary", "sepal", "stamen", "anther", "microspore"):
        assert keyword in flower


def test_wild_type_genotype_token_does_not_block_the_rules():
    # 3,975 samples read "ecotype: Col-0; genotype: wild type genotype" and were
    # sent to the model because "genotype" was not a neutral token.
    values = ["ecotype: Col-0", "genotype: wild type genotype"]
    category, _, source = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category == "natural_accession"
    assert source == "rules"


def test_opaque_genotype_still_abstains():
    values = ["genotype: p6967"]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, GERM_PATTERNS, GERM_RULE_KEYS
    )
    assert category is None


# --- rules layers must ignore paper-level evidence ---------------------------
# `paper_tissue_sampled` and `paper_genotype` normalize to names containing
# "tissue"/"genotype", so a substring match let paper text decide rule labels:
# 1,259 tissue and 1,019 germplasm samples, 189 of them contradicting the
# sample's own genotype.

from evidence import attribute_name, is_project_level  # noqa: E402


def test_attribute_name_normalizes_sra_prefix():
    assert attribute_name("sra_genotype: Col-0") == "genotype"
    assert attribute_name("paper_tissue_sampled: leaf") == "paper tissue sampled"


def test_is_project_level_detects_paper_and_study_lines():
    for line in (
        "paper_genotype: mom1 mutant",
        "paper_tissue_sampled: leaf epidermis",
        "study_title: something",
        "study_abstract: text",
        "experiment_title: sequencing",
        "library_name: lib1",
    ):
        assert is_project_level(line), line
    for line in ("genotype: Col-0", "sra_tissue: leaf", "organism part: root"):
        assert not is_project_level(line), line


def test_tissue_paper_line_alone_does_not_decide():
    values = ["organism: Arabidopsis thaliana", "paper_tissue_sampled: leaf epidermis"]
    assert (
        tissue._rules_category(
            values,
            TISSUE_CATEGORIES_WITH_FLOWER,
            TISSUE_KEYWORDS,
            PO_EXTRA,
            TISSUE_RULE_KEYS,
        )
        is None
    )


def test_tissue_sample_field_beats_paper_line():
    values = ["tissue: root", "paper_tissue_sampled: leaf epidermis"]
    assert (
        tissue._rules_category(
            values,
            TISSUE_CATEGORIES_WITH_FLOWER,
            TISSUE_KEYWORDS,
            PO_EXTRA,
            TISSUE_RULE_KEYS,
        )
        == "root"
    )


def test_germplasm_paper_genotype_alone_does_not_decide():
    values = ["organism: Arabidopsis thaliana", "paper_genotype: mom1 mutant"]
    category, _, _ = germ._rule_label(
        values, GERM_ACCESSIONS, {"mutant": [r"\bmutant\b"]}, GERM_RULE_KEYS
    )
    assert category is None


def test_germplasm_sample_genotype_beats_paper():
    # The paper covers mutant and complemented lines; this sample is wild type.
    values = [
        "ecotype: Col-0",
        "genotype: wild type genotype",
        "paper_genotype: mom1 mutant; miniMOM1 complemented lines",
    ]
    category, _, source = germ._rule_label(
        values, GERM_ACCESSIONS, {"mutant": [r"\bmutant\b"]}, GERM_RULE_KEYS
    )
    assert category == "natural_accession"
    assert source == "rules"


def test_natural_support_ignores_paper_genotype():
    assert germ._natural_supported(
        ["ecotype: Col-0", "paper_genotype: mom1 mutant"], GERM_ACCESSIONS
    )
    # A per-sample genotype with a foreign token still rejects the rule.
    assert not germ._natural_supported(
        ["ecotype: Col-0", "genotype: p6967"], GERM_ACCESSIONS
    )
