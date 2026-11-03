"""Load workflow outputs and PECO terms for the review app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_config(root: Path = REPO_ROOT) -> dict:
    """Read the workflow configuration."""
    path = Path(root) / "config" / "config.yaml"
    with path.open() as handle:
        return yaml.safe_load(handle)


def load_labels(path: Path) -> pd.DataFrame:
    """Read the aggregated annotation table."""
    frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    required = {
        "run",
        "biosample",
        "bioproject",
        "species",
        "review_required",
        "review_reasons",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"labels table is missing columns: {sorted(missing)}")
    if frame["run"].duplicated().any():
        raise ValueError("labels table contains duplicate run accessions")
    return frame


def load_json(path: Path) -> dict | None:
    """Read a JSON file, returning None when it does not exist."""
    path = Path(path)
    if not path.exists():
        return None
    with path.open() as handle:
        return json.load(handle)


def load_terms(index_dir: Path) -> list[dict]:
    """Read the PECO term index used by the workflow."""
    path = Path(index_dir) / "terms.json"
    if not path.exists():
        raise FileNotFoundError(
            f"PECO index not found at {path}; run the workflow index rule first"
        )
    terms = json.loads(path.read_text())
    if not isinstance(terms, list):
        raise ValueError("terms.json must contain a list")
    return terms


def term_index(terms: list[dict]) -> dict[str, dict]:
    """Map PECO term IDs to term records."""
    return {term["id"]: term for term in terms}


def branch_terms(terms: list[dict], branch: str) -> list[dict]:
    """Return terms belonging to an ontology branch."""
    return [term for term in terms if term.get("branch") == branch]


def paper_url(paper: dict | None) -> str | None:
    """Return the best public URL for a linked paper."""
    if not paper:
        return None
    if paper.get("pmcid"):
        return f"https://europepmc.org/article/PMC/{paper['pmcid']}"
    if paper.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/"
    return None


def load_run_bundle(root: Path, sample: dict | Any) -> dict[str, Any]:
    """Load all resources and model outputs for one sample row."""
    root = Path(root)
    run = sample["run"]
    samn = sample["biosample"]
    prjna = sample["bioproject"]
    resources = root / "resources"
    results = root / "results"
    return {
        "sra": load_json(resources / "sra" / f"{run}.json") or {},
        "biosample": load_json(resources / "biosample" / f"{samn}.json") or {},
        "bioproject": load_json(resources / "bioproject" / f"{prjna}.json") or {},
        "paper": load_json(resources / "paper" / f"{prjna}.json") or {},
        "summary": load_json(results / "summary" / f"{prjna}.json") or {},
        "tissue": load_json(results / "tissue" / f"{run}.json") or {},
        "germplasm": load_json(results / "germplasm" / f"{run}.json") or {},
        "exposure": load_json(results / "exposure" / f"{run}.json") or {},
        "study": load_json(results / "study_condition" / f"{run}.json") or {},
        "rna_type": load_json(results / "rna_type" / f"{run}.json") or {},
        "athrdb": load_json(resources / "athrdb" / f"{run}.json") or {},
    }
