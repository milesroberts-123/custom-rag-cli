"""Compute once per window which BioSamples have inconsistent run context.

`sample_rows` needs the set of samples whose runs disagree on experiment title
or library name to add the `mixed_run_context` review reason. Computing it
inside each chunk job meant re-reading every SRA record of the window per
chunk — ~10 minutes per job on Lustre, 625 job-minutes in one window. One
window-level job produces the set instead, and the chunks read a small JSON.
"""

import json
from pathlib import Path

import aggregate


def main():
    groups = [(samn, list(runs)) for samn, runs in snakemake.params.groups]
    mixed = sorted(aggregate.mixed_samples(groups))

    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(mixed, indent=2) + "\n")
    print(
        f"window {snakemake.wildcards.window}: {len(mixed)} of {len(groups)} "
        f"BioSamples have mixed run context"
    )


if __name__ == "__main__":
    main()
