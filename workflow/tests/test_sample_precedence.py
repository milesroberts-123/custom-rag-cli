"""Evidence split and sample-over-project precedence in the labeler prompts.

Every labeling layer follows the same pattern: rules decide from structured
fields, the model handles what rules did not capture, and the model is told to
weigh this sample's own annotation above text shared by the whole project.
PRJEB51241 showed why: a study title reading "... A. thaliana hybrids" made the
model label 382 Inbred samples as hybrids.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import label_germplasm as germ
import label_study_condition as study
import label_tissue as tissue

from evidence import SAMPLE_PRECEDENCE, split_evidence

BIOSAMPLE = {
    "organism": "Arabidopsis thaliana",
    "attributes": {"genotype": "p6967", "is_hybrid": "Inbred"},
}

SRA = {
    "experiment_title": "Illumina HiSeq 3000 sequencing",
    "library_name": "lib-1",
    "sample_name": "sample-1",
    "study_title": "RNA-seq library of A. thaliana hybrids",
    "study_abstract": "We sequenced hybrids and their parents.",
    "sample_attributes": {"replicate": "1"},
}

SUMMARY = {
    "has_paper": True,
    "conditions": {"growth_conditions": "growth chamber", "tissue_sampled": "leaf"},
}


def test_split_evidence_separates_sample_and_project():
    sample, project = split_evidence(BIOSAMPLE, SRA, SUMMARY, ["genotype", "is_hybrid"])

    assert any("genotype: p6967" in line for line in sample)
    assert any("is_hybrid: Inbred" in line for line in sample)
    assert any("library_name: lib-1" in line for line in sample)
    assert any("sra_replicate: 1" in line for line in sample)

    assert any("study_title" in line for line in project)
    assert any("study_abstract" in line for line in project)
    assert any("paper_growth_conditions" in line for line in project)

    # Shared project text must never leak into the per-sample block.
    assert not any("study_title" in line for line in sample)
    assert not any("study_abstract" in line for line in sample)
    assert not any("paper_" in line for line in sample)


def test_split_evidence_honours_attribute_keys():
    sample, _ = split_evidence(BIOSAMPLE, SRA, SUMMARY, ["genotype"])
    assert any(line.startswith("genotype:") for line in sample)
    assert not any(line.startswith("is_hybrid:") for line in sample)


def test_precedence_text_states_that_sample_evidence_outranks_project_text():
    assert "outranks project-level context" in SAMPLE_PRECEDENCE
    assert "never let it override" in SAMPLE_PRECEDENCE


def test_tissue_prompt_carries_the_precedence_rule():
    prompt = tissue.PROMPT.format(
        sample_evidence="organism part: leaf",
        project_evidence="study_title: hybrids",
        sample_precedence=SAMPLE_PRECEDENCE,
        categories="- leaf",
    )
    assert "outranks project-level context" in prompt
    assert "organism part: leaf" in prompt
    assert "study_title: hybrids" in prompt


def test_germplasm_prompt_carries_the_precedence_rule():
    prompt = germ.PROMPT.format(
        sample_evidence="is_hybrid: Inbred",
        project_evidence="study_title: A. thaliana hybrids",
        sample_precedence=SAMPLE_PRECEDENCE,
        categories="- hybrid",
    )
    assert "outranks project-level context" in prompt
    assert "is_hybrid: Inbred" in prompt


def test_study_prompt_allows_project_text_but_keeps_sample_precedence():
    prompt = study.PROMPT.format(
        sample_evidence="tissue: leaf",
        project_evidence="paper_growth_conditions: growth chamber",
        sample_precedence=SAMPLE_PRECEDENCE,
        conditions="- growth chamber study",
    )
    assert "outranks project-level context" in prompt
    # Study condition legitimately relies on Methods text when the sample is silent.
    assert "usually reported only in project-level text" in prompt
    assert "the sample-specific annotation wins" in prompt
