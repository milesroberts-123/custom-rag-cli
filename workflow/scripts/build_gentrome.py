"""Build a decoy-aware Salmon index from a transcriptome and its genome.

Follows Salmon's documented "whole genome as decoy" scheme: the genome is
appended to the transcriptome (gentrome) and the genome sequence names are
listed in ``decoys.txt``. For Arabidopsis the genome is small enough that the
extra index memory is irrelevant, and full decoys are the more comprehensive
of the two documented options.
"""

import gzip
from pathlib import Path


def _open(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def _copy(source, destination):
    """Append a FASTA to the open output, returning the sequence names."""
    names = []
    with _open(source) as handle:
        for line in handle:
            if line.startswith(">"):
                names.append(line[1:].split()[0])
            destination.write(line)
    return names


def main():
    cdna, genome = snakemake.input
    gentrome_path, decoys_path = snakemake.output

    Path(gentrome_path).parent.mkdir(parents=True, exist_ok=True)
    with open(gentrome_path, "w") as out:
        _copy(cdna, out)
        decoys = _copy(genome, out)

    Path(decoys_path).write_text("\n".join(decoys) + "\n")

    LOGGER.info(
        "gentrome built: transcripts from %s, %d decoy sequences from %s",
        Path(cdna).name,
        len(decoys),
        Path(genome).name,
    )


from script_logging import setup as _setup

LOGGER = _setup("build_gentrome")


if __name__ == "__main__":
    main()
