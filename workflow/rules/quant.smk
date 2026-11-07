"""Gene-expression quantification (fasterq-dump/fastp/Salmon) — separate target.

This is not part of ``rule all``: quantification is a second, much heavier
workload with its own resources. Run it with ``snakemake quant_all`` after
``python workflow/scripts/quant_prepare.py`` has written the target list.

Runs of a BioSample are quantified together (Salmon accepts a file list as one
library), so one quant directory per sample carries TPM that is already
comparable — no cross-run TPM recomputation. Samples whose runs differ in
library layout fall back to per-run quantification, summed at merge time.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(workflow.basedir) / "scripts"))

from quant_commands import (  # noqa: E402
    fastp_command,
    salmon_command,
    to_bam_command,
    trimmed_paths,
)

QUANT_TARGETS = Path(config["quant"]["targets"])
QUANT_COLUMNS = [
    "biosample",
    "mode",
    "layout",
    "n_runs",
    "runs",
    "run_layouts",
    "bioproject",
    "species",
]

if QUANT_TARGETS.exists():
    QUANT = pd.read_csv(QUANT_TARGETS, sep="\t", dtype=str).fillna("")
else:
    print(
        f"{QUANT_TARGETS} not found; the quant target is empty. Run "
        "`python workflow/scripts/quant_prepare.py` to build it."
    )
    QUANT = pd.DataFrame(columns=QUANT_COLUMNS)

QUANT_SAMPLES = QUANT["biosample"].tolist() if len(QUANT) else []
QUANT_POOL = [row.biosample for row in QUANT.itertuples() if row.mode == "pool"]
QUANT_PER_RUN_SAMPLES = [
    row.biosample for row in QUANT.itertuples() if row.mode == "per_run"
]
QUANT_RUNS = sorted(
    {
        run
        for runs in QUANT.get("runs", pd.Series(dtype=str))
        for run in str(runs).split(",")
        if run
    }
)

RUNS_WITH_MIXED = sorted(
    {
        run
        for runs in QUANT.loc[QUANT["mode"] == "per_run", "runs"]
        for run in str(runs).split(",")
        if run
    }
)

RUN_LAYOUT = {}
for row in QUANT.itertuples():
    runs = [run for run in str(row.runs).split(",") if run]
    layouts = [value for value in str(row.run_layouts).split(",") if value]
    for run, layout in zip(runs, layouts):
        RUN_LAYOUT[run] = layout


def quant_row(samn):
    """Return the target row for a BioSample."""
    return QUANT.loc[QUANT["biosample"] == samn].iloc[0]


def quant_runs_of(samn):
    """Return the runs belonging to one quantification target."""
    return [run for run in str(quant_row(samn)["runs"]).split(",") if run]


def layout_of(run):
    """Return SINGLE or PAIRED for one run."""
    return RUN_LAYOUT.get(run, "")


QUANT_RUNS_SE = [run for run in QUANT_RUNS if layout_of(run) != "PAIRED"]
QUANT_RUNS_PE = [run for run in QUANT_RUNS if layout_of(run) == "PAIRED"]


def raw_files(run):
    """Raw FASTQ paths for one run, in the layout's canonical shape."""
    if layout_of(run) == "PAIRED":
        return [
            f"results/quant/raw/{run}_R1.fq.gz",
            f"results/quant/raw/{run}_R2.fq.gz",
        ]
    return [f"results/quant/raw/{run}.se.fq.gz"]


def sample_raw(samn):
    """All raw FASTQs for a pooled sample, ordered R1s then R2s."""
    runs = quant_runs_of(samn)
    if layout_of(runs[0]) == "PAIRED":
        left = [f"results/quant/raw/{run}_R1.fq.gz" for run in runs]
        right = [f"results/quant/raw/{run}_R2.fq.gz" for run in runs]
        return left + right
    return [f"results/quant/raw/{run}.se.fq.gz" for run in runs]


def fastp_json(quant_dir, run):
    """Per-run fastp QC report, kept inside the sample's quant directory.

    It lives under the rule's directory output rather than as a separate named
    output: Snakemake 9 rejects output functions, and the sample list is only
    known per wildcard.
    """
    return Path(quant_dir) / "fastp" / f"{run}.fastp.json"


def _trim_dir(quant_dir):
    """Scratch directory for this job's trimmed reads (deleted on success)."""
    return Path(quant_dir) / "trim"


def _trim_and_quant(quant_dir, runs, index, tx2gene, threads, fld_mean, fld_sd):
    """Trim every run of one library, then quantify the pooled library once."""
    layout = layout_of(runs[0])
    trim_dir = _trim_dir(quant_dir)
    shell(f"mkdir -p {trim_dir} {quant_dir}")

    trimmed = []
    for run in runs:
        raw_paths = raw_files(run)
        json_path = fastp_json(quant_dir, run)
        shell(f"mkdir -p {json_path.parent}")
        shell(
            fastp_command(
                run,
                layout,
                raw_paths,
                trim_dir,
                json_path,
                trim_dir / f"{run}.fastp.log",
                threads,
                config["quant"].get("trim_fastq_compress", False),
            )
        )
        trimmed.extend(
            trimmed_paths(
                run,
                layout,
                trim_dir,
                config["quant"].get("trim_fastq_compress", False),
            )
        )

    shell(
        salmon_command(
            quant_dir,
            trimmed,
            layout,
            index,
            tx2gene,
            threads,
            fld_mean,
            fld_sd,
        )
    )
    shell(to_bam_command(quant_dir))
    # Trimmed reads are scratch: the SAM-derived BAM is all TIN needs.
    shell(f"rm -rf {trim_dir}")


rule fetch_cdna:
    output:
        "results/quant/reference/cdna.fa.gz",
    conda:
        "../envs/quant_reads.yaml"
    params:
        url=config["quant"]["cdna_url"],
    shell:
        "mkdir -p results/quant/reference && "
        "curl -fsSL --retry 3 -o {output} {params.url}"


rule fetch_genome:
    output:
        "results/quant/reference/genome.fa.gz",
    conda:
        "../envs/quant_reads.yaml"
    params:
        url=config["quant"]["genome_url"],
    shell:
        "mkdir -p results/quant/reference && "
        "curl -fsSL --retry 3 -o {output} {params.url}"


rule fetch_gtf:
    output:
        "results/quant/reference/annotation.gtf.gz",
    conda:
        "../envs/quant_reads.yaml"
    params:
        url=config["quant"]["gtf_url"],
    shell:
        "mkdir -p results/quant/reference && "
        "curl -fsSL --retry 3 -o {output} {params.url}"


rule build_gentrome:
    input:
        "results/quant/reference/cdna.fa.gz",
        "results/quant/reference/genome.fa.gz",
    output:
        "results/quant/reference/gentrome.fa",
        "results/quant/reference/decoys.txt",
    conda:
        "../envs/quant_py.yaml"
    script:
        "../scripts/build_gentrome.py"


rule salmon_index:
    input:
        "results/quant/reference/gentrome.fa",
        "results/quant/reference/decoys.txt",
    output:
        directory("results/quant/index"),
    conda:
        "../envs/quant_salmon.yaml"
    params:
        k=config["quant"]["salmon_k"],
    shell:
        "salmon index -t {input[0]} -d {input[1]} -i {output} "
        "-k {params.k} -p {threads}"


rule tx2gene:
    input:
        "results/quant/reference/annotation.gtf.gz",
    output:
        "results/quant/tx2gene.tsv",
    conda:
        "../envs/quant_py.yaml"
    script:
        "../scripts/tx2gene.py"


rule fetch_fastq_single:
    input:
        metadata="results/metadata/sra/{run}.json",
    output:
        temp("results/quant/raw/{run}.se.fq.gz"),
    conda:
        "../envs/quant_reads.yaml"
    resources:
        quant_download=1,
    params:
        run="{run}",
        curl="curl",
        prefetch="prefetch",
        fasterq_dump="fasterq-dump",
        pigz="pigz",
        scratch=config["quant"]["scratch"],
    script:
        "../scripts/fetch_fastq.py"


rule fetch_fastq_paired:
    input:
        metadata="results/metadata/sra/{run}.json",
    output:
        temp("results/quant/raw/{run}_R1.fq.gz"),
        temp("results/quant/raw/{run}_R2.fq.gz"),
    conda:
        "../envs/quant_reads.yaml"
    resources:
        quant_download=1,
    params:
        run="{run}",
        curl="curl",
        prefetch="prefetch",
        fasterq_dump="fasterq-dump",
        pigz="pigz",
        scratch=config["quant"]["scratch"],
    script:
        "../scripts/fetch_fastq.py"


rule quant_sample:
    input:
        reads=lambda wildcards: sample_raw(wildcards.samn),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        directory("results/quant/salmon/{samn}"),
    conda:
        "../envs/quant_salmon.yaml"
    params:
        fld_mean=config["quant"]["se_fld_mean"],
        fld_sd=config["quant"]["se_fld_sd"],
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    run:
        _trim_and_quant(
            str(output[0]),
            quant_runs_of(wildcards.samn),
            params.index,
            params.tx2gene,
            threads,
            params.fld_mean,
            params.fld_sd,
        )


rule quant_sample_run:
    input:
        reads=lambda wildcards: raw_files(wildcards.run),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        directory("results/quant/salmon_run/{run}"),
    conda:
        "../envs/quant_salmon.yaml"
    params:
        fld_mean=config["quant"]["se_fld_mean"],
        fld_sd=config["quant"]["se_fld_sd"],
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    run:
        _trim_and_quant(
            str(output[0]),
            [wildcards.run],
            params.index,
            params.tx2gene,
            threads,
            params.fld_mean,
            params.fld_sd,
        )


rule compute_tin:
    input:
        quant_dir="results/quant/salmon/{samn}",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        "results/quant/tin/{samn}.tsv",
        "results/quant/tin/{samn}.json",
    conda:
        "../envs/quant_py.yaml"
    params:
        min_coverage=config["quant"]["tin_min_coverage"],
    script:
        "../scripts/compute_tin.py"


rule compute_tin_run:
    input:
        quant_dir="results/quant/salmon_run/{run}",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        "results/quant/tin_run/{run}.tsv",
        "results/quant/tin_run/{run}.json",
    conda:
        "../envs/quant_py.yaml"
    params:
        min_coverage=config["quant"]["tin_min_coverage"],
    script:
        "../scripts/compute_tin.py"


rule merge_quant:
    input:
        targets=lambda wildcards: (
            [config["quant"]["targets"]]
            if Path(config["quant"]["targets"]).exists()
            else []
        ),
        salmon_dirs=expand("results/quant/salmon/{samn}", samn=QUANT_POOL),
        run_dirs=expand("results/quant/salmon_run/{run}", run=RUNS_WITH_MIXED),
        tin=expand("results/quant/tin/{samn}.json", samn=QUANT_POOL),
        tin_run=expand("results/quant/tin_run/{run}.json", run=RUNS_WITH_MIXED),
        sra=expand("results/metadata/sra/{run}.json", run=QUANT_RUNS),
    output:
        counts="results/quant/gene_counts.tsv",
        tpm="results/quant/gene_tpm.tsv",
        qc="results/quant/quant_qc.tsv",
    conda:
        "../envs/quant_py.yaml"
    script:
        "../scripts/merge_quant.py"


rule quant_all:
    input:
        "results/quant/gene_counts.tsv",
        "results/quant/gene_tpm.tsv",
        "results/quant/quant_qc.tsv",
