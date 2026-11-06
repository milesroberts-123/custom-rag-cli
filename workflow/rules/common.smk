"""Helpers shared by the rule files."""


def samn_of(run):
    """Return the BioSample accession for an SRA run."""
    return SAMPLES.loc[run, "biosample"]


def prjna_of(run):
    """Return the BioProject accession for an SRA run."""
    return SAMPLES.loc[run, "bioproject"]


def species_of(run):
    """Return the species for an SRA run."""
    return SAMPLES.loc[run, "species"]


def biosample_file(wildcards):
    """Input function: normalized BioSample JSON for a run."""
    return f"results/metadata/biosample/{samn_of(wildcards.run)}.json"


def sra_file(wildcards):
    """Input function: normalized SRA metadata JSON for a run."""
    return f"results/metadata/sra/{wildcards.run}.json"


def summary_file(wildcards):
    """Input function: per-project paper summary for a run."""
    return f"results/summary/{prjna_of(wildcards.run)}.json"


def llm_rule_params(model_key, decision=False):
    """Shared Ollama and model params for a labeling rule."""
    params = {
        "model": config["models"][model_key],
        "model_params": config["models"][f"{model_key}_params"],
        "server_url": config["ollama"]["server_url"],
        "api_key": config["ollama"]["api_key"],
    }
    if decision:
        params["backend"] = config["models"][f"{model_key}_backend"]
        params["decision_model"] = config["models"][f"{model_key}_decision"]
    return params


# Labeling is keyed by BioSample, not by run: a sample's tissue, germplasm,
# exposure, and study condition are properties of the biological material, and
# per-run labeling gave runs of the same sample different exposure term sets
# (87% of multi-run samples in the first windows). Runs of a sample are pooled
# as evidence; each run keeps its own row in labels.tsv.
BIOSAMPLES = list(dict.fromkeys(SAMPLES["biosample"]))


def runs_of(samn):
    """Return the SRA runs that belong to one BioSample, in sheet order."""
    return list(SAMPLES.index[SAMPLES["biosample"] == samn])


def prjna_of_samn(samn):
    """Return the BioProject accession for a BioSample."""
    return SAMPLES.loc[runs_of(samn)[0], "bioproject"]


# The labeling rules process BioSamples in chunks: one cluster job per chunk of
# `label_chunk_size` samples. Per-sample output files stay the same, but the
# Python interpreter, torch, and the sentence-transformer encoder load once per
# chunk instead of once per sample, which is where most per-job overhead lives
# at window scale.
LABEL_CHUNK_SIZE = int(config.get("label_chunk_size", 50))
CHUNKS = [
    BIOSAMPLES[i : i + LABEL_CHUNK_SIZE]
    for i in range(0, len(BIOSAMPLES), LABEL_CHUNK_SIZE)
]
CHUNK_IDS = list(range(len(CHUNKS)))


def chunk_samns(wildcards):
    """BioSample accessions handled by one chunk job."""
    return CHUNKS[int(wildcards.chunk)]


def chunk_runs(wildcards):
    """Runs per BioSample for one chunk: a list of run lists."""
    return [runs_of(samn) for samn in chunk_samns(wildcards)]


def chunk_prjnas(wildcards):
    """BioProject accession per BioSample for one chunk."""
    return [prjna_of_samn(samn) for samn in chunk_samns(wildcards)]


def chunk_biosamples(wildcards):
    return [
        f"results/metadata/biosample/{samn}.json" for samn in chunk_samns(wildcards)
    ]


def chunk_sra(wildcards):
    return [
        f"results/metadata/sra/{run}.json"
        for runs in chunk_runs(wildcards)
        for run in runs
    ]


def chunk_summaries(wildcards):
    return [f"results/summary/{prjna}.json" for prjna in chunk_prjnas(wildcards)]


# Exposure labeling is the slowest layer, so it uses smaller chunks than the
# cheap Tev1 layers: 25 samples per job keeps more chunks in flight for the
# same total work (16 slots, ~18 min per chunk instead of ~30).
EXPOSURE_CHUNK_SIZE = int(config.get("exposure_chunk_size", 25))
EXPOSURE_CHUNKS = [
    BIOSAMPLES[i : i + EXPOSURE_CHUNK_SIZE]
    for i in range(0, len(BIOSAMPLES), EXPOSURE_CHUNK_SIZE)
]
EXPOSURE_CHUNK_IDS = list(range(len(EXPOSURE_CHUNKS)))


def exposure_chunk_samns(wildcards):
    """BioSample accessions handled by one exposure chunk job."""
    return EXPOSURE_CHUNKS[int(wildcards.echunk)]


def exposure_chunk_biosamples(wildcards):
    return [
        f"results/metadata/biosample/{samn}.json"
        for samn in exposure_chunk_samns(wildcards)
    ]


def exposure_chunk_runs(wildcards):
    return [runs_of(samn) for samn in exposure_chunk_samns(wildcards)]


def exposure_chunk_sra(wildcards):
    return [
        f"results/metadata/sra/{run}.json"
        for runs in exposure_chunk_runs(wildcards)
        for run in runs
    ]


def exposure_chunk_prjnas(wildcards):
    return [prjna_of_samn(samn) for samn in exposure_chunk_samns(wildcards)]


def exposure_chunk_summaries(wildcards):
    return [
        f"results/summary/{prjna}.json" for prjna in exposure_chunk_prjnas(wildcards)
    ]


def _overlapping_chunks(first_index, count, size, kind):
    """Marker paths for every chunk of `size` samples covering an index range."""
    last_index = first_index + count - 1
    return [
        f"results/chunks/{kind}/{k}.done"
        for k in range(first_index // size, last_index // size + 1)
    ]


def rna_chunks_for_exposure(wildcards):
    """RNA-type markers that must exist before one exposure chunk can run."""
    echunk = int(wildcards.echunk)
    return _overlapping_chunks(
        echunk * EXPOSURE_CHUNK_SIZE,
        len(EXPOSURE_CHUNKS[echunk]),
        LABEL_CHUNK_SIZE,
        "rna_type",
    )


def exposure_chunks_for_sample_rows(wildcards):
    """Exposure markers covering one sample-rows chunk."""
    chunk = int(wildcards.chunk)
    return _overlapping_chunks(
        chunk * LABEL_CHUNK_SIZE,
        len(CHUNKS[chunk]),
        EXPOSURE_CHUNK_SIZE,
        "exposure",
    )
