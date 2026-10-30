"""Combine per-sample tissue, germplasm, and PECO labels into one table."""

import json
from pathlib import Path

import pandas as pd


def _review_reasons(tissue, germplasm, exposure, study, summary, review):
    reasons = []

    if tissue.get("tissue") in (None, "OTHER") or tissue.get("source") == "missing_attributes":
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
    tissue_paths = list(snakemake.input.tissue)
    germplasm_paths = list(snakemake.input.germplasm)
    exposure_paths = list(snakemake.input.exposure)
    study_paths = list(snakemake.input.study)
    if not (
        len(samples)
        == len(tissue_paths)
        == len(germplasm_paths)
        == len(exposure_paths)
        == len(study_paths)
    ):
        raise RuntimeError("sample sheet and label files differ in length")

    terms = {
        term["id"]: term
        for term in json.loads(
            (Path(snakemake.input.index) / "terms.json").read_text()
        )
    }
    review = dict(snakemake.params.review)
    rows = []
    for sample, tissue_path, germplasm_path, exposure_path, study_path in zip(
        samples.itertuples(),
        tissue_paths,
        germplasm_paths,
        exposure_paths,
        study_paths,
    ):
        tissue = json.loads(Path(tissue_path).read_text())
        germplasm = json.loads(Path(germplasm_path).read_text())
        exposure = json.loads(Path(exposure_path).read_text())
        study = json.loads(Path(study_path).read_text())
        summary_path = Path("results/summary") / f"{sample.bioproject}.json"
        summary = (
            json.loads(summary_path.read_text())
            if summary_path.exists()
            else {"has_paper": False, "low_confidence": True}
        )

        growth_terms = [
            term
            for term in exposure.get("terms", [])
            if terms.get(term["term_id"], {}).get("growth_system")
        ]
        reasons = _review_reasons(tissue, germplasm, exposure, study, summary, review)

        rows.append(
            {
                "run": sample.run,
                "biosample": sample.biosample,
                "bioproject": sample.bioproject,
                "species": sample.species,
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
                "growth_system_ids": ";".join(
                    term["term_id"] for term in growth_terms
                ),
                "growth_system_labels": ";".join(
                    term["label"] for term in growth_terms
                ),
                "has_paper": summary.get("has_paper", False),
                "paper_low_confidence": summary.get("low_confidence", True),
                "review_required": bool(reasons),
                "review_reasons": ";".join(reasons),
            }
        )

    frame = pd.DataFrame(rows)
    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, sep="\t", index=False)


if __name__ == "__main__":
    main()
