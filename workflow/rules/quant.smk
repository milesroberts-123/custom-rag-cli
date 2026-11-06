"""Gene-expression quantification (fasterq-dump/fastp/Salmon) — separate target.

This is not part of ``rule all``: quantification is a second, much heavier
workload with its own resources. Run it with ``snakemake quant_all`` after
``python workflow/scripts/quant_prepare.py`` has written the target list.

Runs of a BioSample are quantified together (Salmon accepts a file list as one
library), so one quant directory per sample carries TPM that is already
comparable — no cross-run TPM recomputation. Samples whose runs differ in
library layout fall back to per-run quantification, summed at merge time.
"""

from pathlib import Path

import pandas as pd

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


def trimmed_files(run):
    """Trimmed FASTQ paths for one run, in the layout's canonical shape."""
    if layout_of(run) == "PAIRED":
        return [
            f"results/quant/trimmed/{run}_R1.trim.fq.gz",
            f"results/quant/trimmed/{run}_R2.trim.fq.gz",
        ]
    return [f"results/quant/trimmed/{run}.se.trim.fq.gz"]


def sample_trimmed(samn):
    """All trimmed FASTQs for a pooled sample, ordered R1s then R2s."""
    runs = quant_runs_of(samn)
    if layout_of(runs[0]) == "PAIRED":
        left = [f"results/quant/trimmed/{run}_R1.trim.fq.gz" for run in runs]
        right = [f"results/quant/trimmed/{run}_R2.trim.fq.gz" for run in runs]
        return left + right
    return [f"results/quant/trimmed/{run}.se.trim.fq.gz" for run in runs]


def run_trimmed(run):
    """Trimmed FASTQs for one run (per-run mode)."""
    return trimmed_files(run)


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
        threads=config["quant"]["threads"],
    shell:
        "salmon index -t {input[0]} -d {input[1]} -i {output} "
        "-k {params.k} -p {params.threads}"


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
        "results/quant/raw/{run}.se.fq.gz",
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
        "results/quant/raw/{run}_R1.fq.gz",
        "results/quant/raw/{run}_R2.fq.gz",
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


rule trim_fastq_single:
    input:
        "results/quant/raw/{run}.se.fq.gz",
    output:
        "results/quant/trimmed/{run}.se.trim.fq.gz",
        "results/quant/fastp/se/{run}.fastp.json",
    conda:
        "../envs/quant_reads.yaml"
    params:
        threads=config["quant"]["threads"],
    shell:
        "mkdir -p results/quant/trimmed results/quant/fastp && "
        "fastp -i {input} -o {output[0]} "
        "-w {params.threads} -q 15 -u 40 -l 36 --trim_poly_g "
        "--json {output[1]} "
        "2> results/quant/fastp/se/{wildcards.run}.log"


rule trim_fastq_paired:
    input:
        "results/quant/raw/{run}_R1.fq.gz",
        "results/quant/raw/{run}_R2.fq.gz",
    output:
        "results/quant/trimmed/{run}_R1.trim.fq.gz",
        "results/quant/trimmed/{run}_R2.trim.fq.gz",
        "results/quant/fastp/pe/{run}.fastp.json",
    conda:
        "../envs/quant_reads.yaml"
    params:
        threads=config["quant"]["threads"],
    shell:
        "mkdir -p results/quant/trimmed results/quant/fastp && "
        "fastp -i {input[0]} -I {input[1]} "
        "-o {output[0]} -O {output[1]} "
        "-w {params.threads} -q 15 -u 40 -l 36 --trim_poly_g "
        "--detect_adapter_for_pe --json {output[2]} "
        "2> results/quant/fastp/pe/{wildcards.run}.log"


def salmon_command(output, reads, layout, params):
    """Build the Salmon invocation for one library."""
    parts = [
        "salmon quant",
        f"-i {params['index']}",
        "-l A",
        f"-p {params['threads']}",
        "--gcBias",
        "--seqBias",
        f"-g {params['tx2gene']}",
        f"--writeMappings={output}/mappings.sam",
        f"-o {output}",
    ]
    if layout == "PAIRED":
        half = len(reads) // 2
        parts.append("-1 " + " ".join(reads[:half]))
        parts.append("-2 " + " ".join(reads[half:]))
    else:
        parts.append("-r " + " ".join(reads))
        parts.append(f"--fldMean {params['fld_mean']}")
        parts.append(f"--fldSD {params['fld_sd']}")
    return " ".join(parts)


def to_bam(output):
    """Convert the pseudoalignment SAM to a sorted, indexed BAM."""
    return (
        f"samtools view -b {output}/mappings.sam "
        f"| samtools sort -o {output}/mappings.bam - && "
        f"samtools index {output}/mappings.bam && "
        f"rm -f {output}/mappings.sam"
    )


rule salmon_quant:
    input:
        reads=lambda wildcards: sample_trimmed(wildcards.samn),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        directory("results/quant/salmon/{samn}"),
    conda:
        "../envs/quant_salmon.yaml"
    params:
        threads=config["quant"]["threads"],
        fld_mean=config["quant"]["se_fld_mean"],
        fld_sd=config["quant"]["se_fld_sd"],
        layout=lambda wildcards: layout_of(quant_runs_of(wildcards.samn)[0]),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    run:
        quant_dir = str(output[0])
        shell(f"mkdir -p {quant_dir}")
        shell(
            salmon_command(
                quant_dir,
                list(input.reads),
                params.layout,
                {
                    "index": params.index,
                    "tx2gene": params.tx2gene,
                    "threads": params.threads,
                    "fld_mean": params.fld_mean,
                    "fld_sd": params.fld_sd,
                },
            )
        )
        shell(to_bam(quant_dir))


rule salmon_quant_run:
    input:
        reads=lambda wildcards: run_trimmed(wildcards.run),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    output:
        directory("results/quant/salmon_run/{run}"),
    conda:
        "../envs/quant_salmon.yaml"
    params:
        threads=config["quant"]["threads"],
        fld_mean=config["quant"]["se_fld_mean"],
        fld_sd=config["quant"]["se_fld_sd"],
        layout=lambda wildcards: layout_of(wildcards.run),
        index="results/quant/index",
        tx2gene="results/quant/tx2gene.tsv",
    run:
        quant_dir = str(output[0])
        shell(f"mkdir -p {quant_dir}")
        shell(
            salmon_command(
                quant_dir,
                list(input.reads),
                params.layout,
                {
                    "index": params.index,
                    "tx2gene": params.tx2gene,
                    "threads": params.threads,
                    "fld_mean": params.fld_mean,
                    "fld_sd": params.fld_sd,
                },
            )
        )
        shell(to_bam(quant_dir))


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
        fastp_se=expand("results/quant/fastp/se/{run}.fastp.json", run=QUANT_RUNS_SE),
        fastp_pe=expand("results/quant/fastp/pe/{run}.fastp.json", run=QUANT_RUNS_PE),
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
