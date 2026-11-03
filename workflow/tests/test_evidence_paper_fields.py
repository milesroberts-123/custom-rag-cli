"""Tests for paper summary evidence lines."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evidence import paper_lines


def test_paper_lines_include_day_length_and_temperature():
    summary = {
        "has_paper": True,
        "conditions": {
            "genotype": "Col-0",
            "day_length_hours": 16,
            "growth_temperature_c": 22.5,
            "evidence": "16 h photoperiod at 22.5 C",
        },
    }
    lines = paper_lines(summary)
    assert "paper_genotype: Col-0" in lines
    assert "paper_day_length_hours: 16" in lines
    assert "paper_growth_temperature_c: 22.5" in lines
    assert "paper_evidence: 16 h photoperiod at 22.5 C" in lines


def test_paper_lines_omit_missing_numbers():
    summary = {
        "has_paper": True,
        "conditions": {"genotype": None, "day_length_hours": None},
    }
    lines = paper_lines(summary)
    assert not any(line.startswith("paper_genotype") for line in lines)
    assert not any(line.startswith("paper_day_length") for line in lines)
    assert not any(line.startswith("paper_growth_temperature") for line in lines)


def test_paper_lines_empty_without_paper():
    assert paper_lines({"has_paper": False}) == []
