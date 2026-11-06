"""Compute TIN (transcript integrity number) from Salmon pseudoalignments.

TIN measures how evenly reads cover a transcript: for each covered position,
``TIN = 100 * mean(coverage) / max(coverage)``. A fully covered transcript
scores 100, a library degraded from one end scores low. The sample-level metric
is the median across transcripts with at least ``min_coverage`` reads, which is
the ``medTIN`` used in the RNA-degradation literature.

Coverage comes from Salmon's ``--writeMappings`` BAM, so no second aligner is
needed. Decoy mappings (genome chromosomes) and non-unique mappings are
skipped: they would inflate coverage without representing transcript reads.
"""

import json
import math
from pathlib import Path


def _transcript_ids(path):
    """Return the set of transcript identifiers from the tx2gene table."""
    ids = set()
    with open(path) as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if fields and fields[0]:
                ids.add(fields[0])
    return ids


def _gene_of(path):
    mapping = {}
    with open(path) as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 2:
                mapping[fields[0]] = fields[1]
    return mapping


def _coverage(bam_path, transcripts):
    """Return {transcript: (coverage list, read count)} from a pseudoalignment BAM."""
    import pysam  # imported here so the TIN maths can be tested without pysam

    coverage = {}
    reads = {}
    with pysam.AlignmentFile(bam_path, "rb") as bam:
        for read in bam:
            if read.is_unmapped or read.is_secondary or read.is_supplementary:
                continue
            reference = bam.get_reference_name(read.reference_id)
            if reference not in transcripts:
                continue
            nh = read.get_tag("NH") if read.has_tag("NH") else 1
            if nh != 1:
                continue
            span = coverage.get(reference)
            if span is None:
                span = [0] * bam.get_reference_length(reference)
                coverage[reference] = span
            for start, end in read.get_blocks():
                if start < 0:
                    start = 0
                if end > len(span):
                    end = len(span)
                for position in range(start, end):
                    span[position] += 1
            reads[reference] = reads.get(reference, 0) + 1
    return coverage, reads


def _tin(values):
    if not values:
        return 0.0
    maximum = max(values)
    if maximum <= 0:
        return 0.0
    return 100.0 * (sum(values) / len(values)) / maximum


def _skew(values):
    """log2 of 5' vs 3' coverage; negative means 3'-depleted (degraded)."""
    length = len(values)
    if length < 20:
        return None
    window = max(1, length // 10)
    head = sum(values[:window]) / window
    tail = sum(values[-window:]) / window
    return round(math.log2((head + 1.0) / (tail + 1.0)), 4)


def main():
    bam_path = str(Path(snakemake.input.quant_dir) / "mappings.bam")
    tx2gene = snakemake.input.tx2gene
    min_coverage = int(snakemake.params.min_coverage)

    transcripts = _transcript_ids(tx2gene)
    genes = _gene_of(tx2gene)
    coverage, reads = _coverage(bam_path, transcripts)

    rows = []
    for transcript, values in coverage.items():
        n_reads = reads.get(transcript, 0)
        if n_reads < min_coverage:
            continue
        rows.append(
            (
                transcript,
                genes.get(transcript, ""),
                len(values),
                n_reads,
                _tin(values),
                _skew(values),
            )
        )

    rows.sort(key=lambda row: row[4], reverse=True)
    tsv_path, json_path = snakemake.output
    Path(tsv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(tsv_path, "w") as out:
        out.write("transcript\tgene\tlength\treads\tTIN\tskew\n")
        for row in rows:
            out.write(
                "\t".join(
                    [
                        row[0],
                        row[1],
                        str(row[2]),
                        str(row[3]),
                        f"{row[4]:.4f}",
                        "" if row[5] is None else f"{row[5]:.4f}",
                    ]
                )
                + "\n"
            )

    tins = sorted(row[4] for row in rows)
    if tins:
        middle = len(tins) // 2
        median = (
            tins[middle] if len(tins) % 2 else (tins[middle - 1] + tins[middle]) / 2
        )
    else:
        median = None
    skews = sorted(row[5] for row in rows if row[5] is not None)
    summary = {
        "medTIN": None if median is None else round(median, 4),
        "n_transcripts": len(tins),
        "min_coverage": min_coverage,
        "p10": round(tins[int(0.1 * len(tins))], 4) if tins else None,
        "p90": round(tins[int(0.9 * len(tins))], 4) if tins else None,
        "median_skew": round(skews[len(skews) // 2], 4) if skews else None,
    }
    Path(json_path).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    LOGGER.info(
        "TIN: medTIN=%s across %d transcripts (min coverage %d)",
        summary["medTIN"],
        summary["n_transcripts"],
        min_coverage,
    )


from script_logging import setup as _setup

LOGGER = _setup("compute_tin")


if __name__ == "__main__":
    main()
