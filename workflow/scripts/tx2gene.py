"""Extract a transcript-to-gene map from an Ensembl GTF.

Output is a two-plus column TSV (transcript_id, gene_id, gene_name) that Salmon
consumes with ``--geneMap`` to emit gene-level quantification alongside the
transcript-level one. The annotation release must match the cDNA FASTA used for
the index, or transcript IDs will not line up.
"""

import gzip
import re
from pathlib import Path

TRANSCRIPT_ID = re.compile(r'transcript_id "([^"]+)"')
GENE_ID = re.compile(r'gene_id "([^"]+)"')
GENE_NAME = re.compile(r'gene_name "([^"]+)"')


def parse_gtf(gtf_path):
    """Yield (transcript_id, gene_id, gene_name) for each transcript row."""
    opener = gzip.open if str(gtf_path).endswith(".gz") else open
    seen = set()
    with opener(gtf_path, "rt") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9 or fields[2] != "transcript":
                continue
            attributes = fields[8]
            transcript = TRANSCRIPT_ID.search(attributes)
            gene = GENE_ID.search(attributes)
            if not transcript or not gene:
                continue
            if transcript.group(1) in seen:
                continue
            seen.add(transcript.group(1))
            name = GENE_NAME.search(attributes)
            yield (
                transcript.group(1),
                gene.group(1),
                name.group(1) if name else "",
            )


def main():
    gtf_path = snakemake.input[0]
    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output, "w") as out:
        for transcript, gene, name in parse_gtf(gtf_path):
            out.write("\t".join([transcript, gene, name]) + "\n")
            written += 1
    LOGGER.info("tx2gene: %d transcripts", written)


from script_logging import setup as _setup

LOGGER = _setup("tx2gene")


if __name__ == "__main__":
    main()
