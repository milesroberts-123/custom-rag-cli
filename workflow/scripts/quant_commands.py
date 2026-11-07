"""Shell-command builders for the quantification rules.

Kept as pure functions (no Snakemake globals) so the commands can be unit
tested: thread counts, compression, and paired/single branching are exactly the
places where a wrong flag silently wastes hours of cluster time.
"""

from pathlib import Path


def trim_suffix(compress):
    """Suffix for trimmed FASTQ files: ``.fq.gz`` when compressing, else ``.fq``."""
    return ".fq.gz" if compress else ".fq"


def fastp_command(run, layout, raw, out_dir, json_path, log_path, threads, compress):
    """Build the fastp command for one run.

    Adapter trimming only: ``--dedup`` is deliberately never passed, because
    duplicate reads in RNA-seq are usually biological. ``--detect_adapter_for_pe``
    is needed for paired-end libraries, whose adapters fastp cannot infer from
    the reads alone.
    """
    suffix = trim_suffix(compress)
    out_dir = Path(out_dir)
    if layout == "PAIRED":
        trimmed = [
            out_dir / f"{run}_R1{suffix}",
            out_dir / f"{run}_R2{suffix}",
        ]
        return (
            f"fastp -i {raw[0]} -I {raw[1]} "
            f"-o {trimmed[0]} -O {trimmed[1]} "
            f"-w {threads} -q 15 -u 40 -l 36 --trim_poly_g "
            f"--detect_adapter_for_pe --json {json_path} 2> {log_path}"
        )
    trimmed = out_dir / f"{run}.se{suffix}"
    return (
        f"fastp -i {raw[0]} -o {trimmed} "
        f"-w {threads} -q 15 -u 40 -l 36 --trim_poly_g "
        f"--json {json_path} 2> {log_path}"
    )


def trimmed_paths(run, layout, out_dir, compress):
    """Trimmed FASTQ paths that :func:`fastp_command` writes for one run."""
    suffix = trim_suffix(compress)
    out_dir = Path(out_dir)
    if layout == "PAIRED":
        return [out_dir / f"{run}_R1{suffix}", out_dir / f"{run}_R2{suffix}"]
    return [out_dir / f"{run}.se{suffix}"]


def salmon_command(
    output,
    reads,
    layout,
    index,
    tx2gene,
    threads,
    fld_mean,
    fld_sd,
    write_mappings=True,
):
    """Build the Salmon invocation for one pooled library.

    Salmon accepts a space-separated list of files as a single library, which is
    how the runs of one BioSample are quantified together: TPM then describes
    the pooled library and needs no post-hoc recomputation.
    """
    parts = [
        "salmon quant",
        f"-i {index}",
        "-l A",
        f"-p {threads}",
        "--gcBias",
        "--seqBias",
        f"-g {tx2gene}",
        f"-o {output}",
    ]
    if write_mappings:
        parts.append(f"--writeMappings={output}/mappings.sam")
    if layout == "PAIRED":
        half = len(reads) // 2
        parts.append("-1 " + " ".join(str(path) for path in reads[:half]))
        parts.append("-2 " + " ".join(str(path) for path in reads[half:]))
    else:
        parts.append("-r " + " ".join(str(path) for path in reads))
        parts.append(f"--fldMean {fld_mean}")
        parts.append(f"--fldSD {fld_sd}")
    return " ".join(parts)


def to_bam_command(output):
    """Convert the pseudoalignment SAM to a sorted, indexed BAM for TIN."""
    return (
        f"samtools view -b {output}/mappings.sam "
        f"| samtools sort -o {output}/mappings.bam - && "
        f"samtools index {output}/mappings.bam && "
        f"rm -f {output}/mappings.sam"
    )
