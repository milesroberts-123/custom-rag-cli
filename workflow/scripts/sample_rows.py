"""Build the aggregation fragment for one window and chunk.

Each chunk writes one TSV row per run of its BioSamples, so the final
`aggregate` step only concatenates fragments. Doing the per-run work here —
inside the window that produced the labels — keeps total cost proportional to
the number of samples labeled rather than to the whole sheet on every run.
"""

import json
import sys
from pathlib import Path

import aggregate
import pandas as pd


def main():
    sheet = pd.read_table(snakemake.params.samples, dtype=str)
    terms = {
        term["id"]: term
        for term in json.loads((Path(snakemake.input.index) / "terms.json").read_text())
    }

    written = aggregate.build_rows(
        sheet,
        snakemake.params.samns,
        dict(snakemake.params.review),
        terms,
        window=snakemake.wildcards.window,
        destination=snakemake.output[0],
    )
    print(
        f"window {snakemake.wildcards.window} chunk {snakemake.wildcards.chunk}: "
        f"{written} run rows",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
