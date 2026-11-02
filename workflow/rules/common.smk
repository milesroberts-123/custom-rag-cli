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
    return f"resources/biosample/{samn_of(wildcards.run)}.json"


def sra_file(wildcards):
    """Input function: normalized SRA metadata JSON for a run."""
    return f"resources/sra/{wildcards.run}.json"


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
