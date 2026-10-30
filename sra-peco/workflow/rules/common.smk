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


def summary_file(wildcards):
    """Input function: per-project paper summary for a run."""
    return f"results/summary/{prjna_of(wildcards.run)}.json"
