"""Combine per-sample tissue, germplasm, and PECO labels into one table."""

import json
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


def _review_reasons(tissue, germplasm, exposure, study, summary, rna_type, review):
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
    return list(dict.fromkeys(reasons))


def main():
    samples = pd.read_table(snakemake.params.samples, dtype=str)
    rna_type_paths = list(snakemake.input.rna_type)
    tissue_paths = list(snakemake.input.tissue)
    germplasm_paths = list(snakemake.input.germplasm)
    exposure_paths = list(snakemake.input.exposure)
    study_paths = list(snakemake.input.study)
    athrdb_paths = list(snakemake.input.athrdb)
    if not (
        len(samples)
        == len(rna_type_paths)
        == len(tissue_paths)
        == len(germplasm_paths)
        == len(exposure_paths)
        == len(study_paths)
        == len(athrdb_paths)
    ):
        raise RuntimeError("sample sheet and label files differ in length")

    terms = {
        term["id"]: term
        for term in json.loads((Path(snakemake.input.index) / "terms.json").read_text())
    }
    review = dict(snakemake.params.review)
    rows = []
    excluded = []
    for (
        sample,
        rna_type_path,
        tissue_path,
        germplasm_path,
        exposure_path,
        study_path,
        athrdb_path,
    ) in zip(
        samples.itertuples(),
        rna_type_paths,
        tissue_paths,
        germplasm_paths,
        exposure_paths,
        study_paths,
        athrdb_paths,
    ):
        rna_type = json.loads(Path(rna_type_path).read_text())
        if not rna_type.get("mrna_eligible", False):
            excluded.append(
                {
                    "run": sample.run,
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

        tissue = json.loads(Path(tissue_path).read_text())
        germplasm = json.loads(Path(germplasm_path).read_text())
        exposure = json.loads(Path(exposure_path).read_text())
        study = json.loads(Path(study_path).read_text())
        athrdb = json.loads(Path(athrdb_path).read_text())
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
            tissue, germplasm, exposure, study, summary, rna_type, review
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
