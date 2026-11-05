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


def rna_type_file(wildcards):
    """Input function: RNA type classification for a run."""
    return f"results/rna_type/{wildcards.run}.json"


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


# The four label rules process runs in chunks: one cluster job per chunk of
# `label_chunk_size` runs. Per-run output files stay the same, but the Python
# interpreter, torch, and the sentence-transformer encoder load once per
# chunk instead of once per run, which is where most per-job overhead lives
# at window scale.
LABEL_CHUNK_SIZE = int(config.get("label_chunk_size", 50))
CHUNKS = [RUNS[i : i + LABEL_CHUNK_SIZE] for i in range(0, len(RUNS), LABEL_CHUNK_SIZE)]
CHUNK_IDS = list(range(len(CHUNKS)))


def chunk_runs(wildcards):
    """Return the run accessions handled by one label chunk job."""
    return CHUNKS[int(wildcards.chunk)]


def chunk_samns(wildcards):
    """BioSample accessions for one chunk, in run order."""
    return [samn_of(run) for run in chunk_runs(wildcards)]


def chunk_prjnas(wildcards):
    """BioProject accessions for one chunk, in run order."""
    return [prjna_of(run) for run in chunk_runs(wildcards)]


def chunk_rna_types(wildcards):
    return [f"results/rna_type/{run}.json" for run in chunk_runs(wildcards)]


def chunk_biosamples(wildcards):
    return [
        f"results/metadata/biosample/{samn}.json" for samn in chunk_samns(wildcards)
    ]


def chunk_sra(wildcards):
    return [f"results/metadata/sra/{run}.json" for run in chunk_runs(wildcards)]


def chunk_summaries(wildcards):
    return [f"results/summary/{prjna}.json" for prjna in chunk_prjnas(wildcards)]
