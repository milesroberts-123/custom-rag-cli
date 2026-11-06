"""Tests for the hardened exposure prompt and evidence split."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# label_exposure imports sentence_transformers (CPU torch) at module level;
# stub it so this prompt-structure test does not need the heavy dependency.
_st = types.ModuleType("sentence_transformers")


class _SentenceTransformer:  # pragma: no cover
    pass


_st.SentenceTransformer = _SentenceTransformer
sys.modules["sentence_transformers"] = _st

import label_exposure as exposure

from evidence import exposure_evidence

BIOSAMPLE = {
    "organism": "Arabidopsis thaliana",
    "attributes": {"tissue": "leaf", "developmental stage": "rosette"},
}

SRA = {
    "experiment_title": "warm temperature treatment",
    "library_name": "Warm_T_1_p",
    "sample_name": "Warm_T_1",
    "study_title": "Thermal response of Arabidopsis",
    "study_abstract": "Plants were exposed to warm temperature or kept as controls.",
    "sample_attributes": {"temperature": "30C"},
}

SUMMARY = {
    "has_paper": True,
    "conditions": {"treatment": "warm temperature", "stress": None},
}


def test_exposure_evidence_split():
    sample, project = exposure_evidence(BIOSAMPLE, SRA, SUMMARY)
    assert any("library_name: Warm_T_1_p" in line for line in sample)
    assert any("sra_temperature: 30C" in line for line in sample)
    assert any("tissue: leaf" in line for line in sample)
    assert any("study_title" in line for line in project)
    assert any("study_abstract" in line for line in project)
    assert any("paper_treatment" in line for line in project)
    # project-level text must not leak into the per-sample block
    assert not any("study_abstract" in line for line in sample)
    assert not any("paper_" in line for line in sample)


def test_prompt_has_both_blocks_and_hardening_rules():
    prompt = exposure.PROMPT.format(
        sample_evidence="library_name: Warm_T_1_p",
        project_evidence="study_abstract: ...",
        candidates="- PECO:0007175 | temperature exposure | ...",
    )
    assert "Per-sample evidence" in prompt
    assert "Project-level context" in prompt
    assert "never the sole basis" in prompt
    assert 'Do not co-select "temperature exposure"' in prompt
    assert 'prefer the "control exposure" term' in prompt
    assert "library_name: Warm_T_1_p" in prompt
