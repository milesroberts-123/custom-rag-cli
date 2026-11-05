"""Combine per-sample tissue, germplasm, and PECO labels into one table.

With window batching, this script rescans the full sample sheet every
invocation and includes every run whose label files are complete on disk, so
results/labels.tsv and results/labels.excluded.tsv accumulate across windows.
Runs with an RNA-type record but an incomplete label set are counted and
reported, never silently dropped; rerun their window to finish them.
"""

import json
import sys
from pathlib import Path

import pandas as pd

LABEL_COLUMNS = [
    "run",
    "biosample",
    "bioproject",
    "species",
    "rna_type",
    "rna_subtype",
    "ribo_depleted",
    "mrna_eligible",
    "rna_type_source",
    "rna_type_confidence",
    "rna_type_evidence",
    "tissue",
    "tissue_source",
    "tissue_confidence",
    "germplasm_type",
    "is_natural_accession",
    "germplasm_confidence",
    "germplasm_evidence",
    "peco_exposure_ids",
    "peco_exposure_labels",
    "peco_exposure_evidence",
    "peco_exposure_other",
    "peco_exposure_max_score",
    "peco_study_id",
    "peco_study_label",
    "peco_study_confidence",
    "growth_system_ids",
    "growth_system_labels",
    "has_paper",
    "paper_low_confidence",
    "paper_day_length_hours",
    "paper_growth_temperature_c",
    "athrdb_gsm",
    "athrdb_tissue",
    "athrdb_genotype",
    "athrdb_ecotype",
    "review_required",
    "review_reasons",
]

EXCLUDED_COLUMNS = [
    "run",
    "biosample",
    "bioproject",
    "species",
    "rna_type",
    "rna_subtype",
    "ribo_depleted",
    "rna_type_source",
    "rna_type_confidence",
    "rna_type_evidence",
    "exclusion_reason",
]


def _exclusion_reason(rna_type):
    category = rna_type.get("rna_type") or "unknown"
    if category == "unknown":
        return "rna_type_unknown"
    if category == "not_rna":
        return "not_rna_assay"
    return f"rna_type_{category}_not_accepted"


def _tissues_agree(curated, model):
    """Loose tissue comparison: AthRDB uses a finer vocabulary than ours."""
    curated, model = curated.lower().strip(), model.lower().strip()
    if curated == model:
        return True
    synonyms = {
        "rosette": "leaf",
        "rosette leaf": "leaf",
        "leaf rosette": "leaf",
        "rosette leaves": "leaf",
    }
    return synonyms.get(curated) == model or synonyms.get(model) == curated


def _athrdb_crosscheck(athrdb, tissue, germplasm):
    """Compare AthRDB curation against the model labels; True when they clash.

    The labelers do not see AthRDB anymore; this is the independent-curation
    review signal. Only `athrdb_hit` records are compared, and only when both
    sides have a concrete value.
    """
    if not athrdb.get("athrdb_hit"):
        return False

    curated_tissue = (athrdb.get("athrdb_tissue") or "").strip()
    model_tissue = str(tissue.get("tissue") or "")
    if (
        curated_tissue
        and model_tissue
        and model_tissue != "OTHER"
        and not _tissues_agree(curated_tissue, model_tissue)
    ):
        return True

    curated_genotype = (athrdb.get("athrdb_genotype") or "").strip()
    model_germplasm = germplasm.get("germplasm_type")
    if curated_genotype and model_germplasm not in (None, "", "unknown"):
        curated_natural = "wild" in curated_genotype.lower()
        model_natural = model_germplasm == "natural_accession"
        if curated_natural != model_natural:
            return True
    return False


def _review_reasons(
    tissue, germplasm, exposure, study, summary, rna_type, athrdb, review
):
    reasons = []

    confidence = rna_type.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["rna_type_confidence"]
    ):
        reasons.append("rna_type_low_confidence")

    if (
        tissue.get("tissue") in (None, "OTHER")
        or tissue.get("source") == "missing_attributes"
    ):
        reasons.append("tissue_other")
    confidence = tissue.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["tissue_confidence"]
    ):
        reasons.append("tissue_low_confidence")

    if germplasm.get("germplasm_type") in (None, "unknown"):
        reasons.append("germplasm_unknown")
    confidence = germplasm.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["germplasm_confidence"]
    ):
        reasons.append("germplasm_low_confidence")

    if exposure.get("other"):
        reasons.append("exposure_other")
    score = exposure.get("max_retrieval_score")
    if isinstance(score, (int, float)) and score < float(
        review["exposure_retrieval_score"]
    ):
        reasons.append("exposure_weak_retrieval")

    if study.get("other") or study.get("label") in (None, "OTHER"):
        reasons.append("study_other")
    confidence = study.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["study_confidence"]
    ):
        reasons.append("study_low_confidence")

    if review["flag_missing_paper"] and not summary.get("has_paper", False):
        reasons.append("no_paper")
    elif review["flag_low_confidence_paper"] and summary.get("low_confidence", False):
        reasons.append("paper_low_confidence")

    if review.get("athrdb_crosscheck", True) and _athrdb_crosscheck(
        athrdb, tissue, germplasm
    ):
        reasons.append("athrdb_disagreement")
    return list(dict.fromkeys(reasons))


LABEL_KINDS = ("tissue", "germplasm", "exposure", "study_condition")


def _run_path(kind, run):
    """Path to one run's per-kind record under results/."""
    if kind == "athrdb":
        return Path("results/metadata/athrdb") / f"{run}.json"
    return Path("results") / kind / f"{run}.json"


def main():
    sheet = pd.read_table(snakemake.params.samples, dtype=str)

    terms = {
        term["id"]: term
        for term in json.loads((Path(snakemake.input.index) / "terms.json").read_text())
    }
    review = dict(snakemake.params.review)

    rows = []
    excluded = []
    incomplete = []
    for sample in sheet.itertuples():
        run = sample.run
        rna_type_path = _run_path("rna_type", run)
        if not rna_type_path.exists():
            # Not yet classified: belongs to a window that has not run.
            incomplete.append(run)
            continue
        rna_type = json.loads(rna_type_path.read_text())

        if not rna_type.get("mrna_eligible", False):
            excluded.append(
                {
                    "run": run,
                    "biosample": sample.biosample,
                    "bioproject": sample.bioproject,
                    "species": sample.species,
                    "rna_type": rna_type.get("rna_type"),
                    "rna_subtype": rna_type.get("rna_subtype") or "",
                    "ribo_depleted": bool(rna_type.get("ribo_depleted", False)),
                    "rna_type_source": rna_type.get("source", ""),
                    "rna_type_confidence": rna_type.get("confidence"),
                    "rna_type_evidence": rna_type.get("evidence", ""),
                    "exclusion_reason": _exclusion_reason(rna_type),
                }
            )
            continue

        # Eligible runs need their full label set plus the ATHRDB record.
        paths = {kind: _run_path(kind, run) for kind in LABEL_KINDS}
        athrdb_path = _run_path("athrdb", run)
        missing = [kind for kind, path in paths.items() if not path.exists()]
        if missing or not athrdb_path.exists():
            incomplete.append(run)
            continue

        tissue = json.loads(paths["tissue"].read_text())
        germplasm = json.loads(paths["germplasm"].read_text())
        exposure = json.loads(paths["exposure"].read_text())
        study = json.loads(paths["study_condition"].read_text())
        athrdb = json.loads(athrdb_path.read_text())
        summary_path = Path("results/summary") / f"{sample.bioproject}.json"
        summary = (
            json.loads(summary_path.read_text())
            if summary_path.exists()
            else {"has_paper": False, "low_confidence": True}
        )
        conditions = summary.get("conditions") or {}

        growth_terms = [
            term
            for term in exposure.get("terms", [])
            if terms.get(term["term_id"], {}).get("growth_system")
        ]
        reasons = _review_reasons(
            tissue, germplasm, exposure, study, summary, rna_type, athrdb, review
        )

        rows.append(
            {
                "run": sample.run,
                "biosample": sample.biosample,
                "bioproject": sample.bioproject,
                "species": sample.species,
                "rna_type": rna_type.get("rna_type"),
                "rna_subtype": rna_type.get("rna_subtype") or "",
                "ribo_depleted": bool(rna_type.get("ribo_depleted", False)),
                "mrna_eligible": True,
                "rna_type_source": rna_type.get("source", ""),
                "rna_type_confidence": rna_type.get("confidence"),
                "rna_type_evidence": rna_type.get("evidence", ""),
                "tissue": tissue.get("tissue"),
                "tissue_source": tissue.get("source"),
                "tissue_confidence": tissue.get("confidence"),
                "germplasm_type": germplasm.get("germplasm_type"),
                "is_natural_accession": germplasm.get("is_natural_accession"),
                "germplasm_confidence": germplasm.get("confidence"),
                "germplasm_evidence": germplasm.get("evidence"),
                "peco_exposure_ids": ";".join(
                    term["term_id"] for term in exposure.get("terms", [])
                ),
                "peco_exposure_labels": ";".join(
                    term["label"] for term in exposure.get("terms", [])
                ),
                "peco_exposure_evidence": " | ".join(
                    term["evidence"] for term in exposure.get("terms", [])
                ),
                "peco_exposure_other": exposure.get("other", False),
                "peco_exposure_max_score": exposure.get("max_retrieval_score"),
                "peco_study_id": study.get("term_id"),
                "peco_study_label": study.get("label"),
                "peco_study_confidence": study.get("confidence"),
                "growth_system_ids": ";".join(term["term_id"] for term in growth_terms),
                "growth_system_labels": ";".join(
                    term["label"] for term in growth_terms
                ),
                "has_paper": summary.get("has_paper", False),
                "paper_low_confidence": summary.get("low_confidence", True),
                "paper_day_length_hours": conditions.get("day_length_hours"),
                "paper_growth_temperature_c": conditions.get("growth_temperature_c"),
                "athrdb_gsm": athrdb.get("gsm"),
                "athrdb_tissue": athrdb.get("athrdb_tissue"),
                "athrdb_genotype": athrdb.get("athrdb_genotype"),
                "athrdb_ecotype": athrdb.get("athrdb_ecotype"),
                "review_required": bool(reasons),
                "review_reasons": ";".join(reasons),
            }
        )

    if incomplete:
        print(
            f"{len(incomplete)} of {len(sheet)} sheet runs are not aggregated "
            f"yet ({'; '.join(incomplete[:5])}"
            f"{'...' if len(incomplete) > 5 else ''}); rerun their window to "
            "finish them.",
            file=sys.stderr,
        )

    frame = pd.DataFrame(rows, columns=LABEL_COLUMNS)
    output = Path(snakemake.output.labels)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, sep="\t", index=False)

    excluded_frame = pd.DataFrame(excluded, columns=EXCLUDED_COLUMNS)
    excluded_output = Path(snakemake.output.excluded)
    excluded_output.parent.mkdir(parents=True, exist_ok=True)
    excluded_frame.to_csv(excluded_output, sep="\t", index=False)


if __name__ == "__main__":
    main()
