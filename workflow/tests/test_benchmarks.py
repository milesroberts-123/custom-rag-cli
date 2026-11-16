"""Every rule must declare a benchmark, so filesystem comparisons stay possible.

The benchmarks feed the Lustre-vs-VAST comparison: each job writes wall time,
max RSS, and io_in/io_out under `benchmark_dir`. A rule without the directive
silently drops out of that comparison, so this test parses the rule files and
fails when the directive is missing.
"""

import re
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

# Target/aggregator rules have no job of their own and cannot benchmark.
EXEMPT = {"quant_all"}


def _rules():
    """Yield ``(file, rule_name, source)`` for every rule in workflow/rules."""
    for path in sorted(RULES_DIR.glob("*.smk")):
        text = path.read_text()
        blocks = re.split(r"(?m)^rule ", text)
        for block in blocks[1:]:
            name = block.split(":", 1)[0].strip()
            yield path, name, block


def test_every_rule_declares_a_benchmark():
    missing = [
        f"{path.name}:{name}"
        for path, name, block in _rules()
        if name not in EXEMPT and not re.search(r"(?m)^    benchmark:", block)
    ]
    assert not missing, "rules without a benchmark directive: " + ", ".join(missing)


def test_chunked_rules_scope_benchmarks_by_window():
    """Chunk ids repeat every window, so a benchmark keyed only by chunk wins
    the last window and loses the rest."""
    chunked = {
        "classify_rna_type",
        "label_tissue",
        "label_germplasm",
        "label_study_condition",
    }
    exposure = {"label_exposure"}
    for _path, name, block in _rules():
        if name in chunked:
            assert (
                "WINDOW_INDEX}-{{chunk}}" in block
                or "WINDOW_INDEX}-{{echunk}}" in block
            ), name
        elif name in exposure:
            assert "WINDOW_INDEX}-{{echunk}}" in block, name


def test_benchmark_paths_come_from_the_helper():
    for path, name, block in _rules():
        if name in EXEMPT:
            continue
        match = re.search(r"(?m)^    benchmark:\n        (.*)$", block)
        assert match, name
        assert match.group(1).startswith("benchmark("), (
            f"{path.name}:{name} bypasses the helper"
        )
