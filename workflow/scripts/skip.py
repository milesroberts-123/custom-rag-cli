"""Short-circuit label rules for runs that are not mRNA-eligible."""

import json
from pathlib import Path


def load_rna_type(path):
    """Read the RNA type record for a run."""
    with open(path) as handle:
        return json.load(handle)


def write_skip(run, rna_type, output):
    """Write a minimal label stub for an excluded run."""
    result = {
        "run": run,
        "skipped": True,
        "reason": "not_mrna",
        "rna_type": rna_type.get("rna_type"),
        "rna_subtype": rna_type.get("rna_subtype"),
        "mrna_eligible": False,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
