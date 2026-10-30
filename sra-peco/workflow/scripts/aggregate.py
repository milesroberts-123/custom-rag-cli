"""Combine per-sample tissue and PECO labels into one table."""

import json
from pathlib import Path

import pandas as pd


def _review_reasons(tissue, peco, summary, review):
    reasons = []
    if tissue.get("tissue") in (None, "OTHER") or tissue.get("source") == "missing_attributes":
        reasons.append("tissue_other")

    confidence = tissue.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["tissue_confidence"]
    ):
        reasons.append("tissue_low_confidence")

    if peco.get("other"):
        reasons.append("peco_other")

    score = peco.get("max_retrieval_score")
    if isinstance(score, (int, float)) and score < float(
        review["peco_retrieval_score"]
    ):
        reasons.append("peco_weak_retrieval")

    if review["flag_missing_paper"] and not summary.get("has_paper", False):
        reasons.append("no_paper")
    elif review["flag_low_confidence_paper"] and summary.get("low_confidence", False):
        reasons.append("paper_low_confidence")
    return reasons


def main():
    samples = pd.read_table(snakemake.params.samples, dtype=str)
    tissue_paths = list(snakemake.input.tissue)
    peco_paths = list(snakemake.input.peco)
    if not (len(samples) == len(tissue_paths) == len(peco_paths)):
        raise RuntimeError("sample sheet and label files differ in length")

    review = dict(snakemake.params.review)
    rows = []
    for sample, tissue_path, peco_path in zip(
        samples.itertuples(), tissue_paths, peco_paths
    ):
        tissue = json.loads(Path(tissue_path).read_text())
        peco = json.loads(Path(peco_path).read_text())
        summary_path = Path("results/summary") / f"{sample.bioproject}.json"
        summary = (
            json.loads(summary_path.read_text())
            if summary_path.exists()
            else {"has_paper": False, "low_confidence": True}
        )
        reasons = _review_reasons(tissue, peco, summary, review)
        rows.append(
            {
                "run": sample.run,
                "biosample": sample.biosample,
                "bioproject": sample.bioproject,
                "species": sample.species,
                "tissue": tissue.get("tissue"),
                "tissue_source": tissue.get("source"),
                "tissue_confidence": tissue.get("confidence"),
                "peco_term_ids": ";".join(
                    term["term_id"] for term in peco.get("terms", [])
                ),
                "peco_labels": ";".join(
                    term["label"] for term in peco.get("terms", [])
                ),
                "peco_evidence": " | ".join(
                    term["evidence"] for term in peco.get("terms", [])
                ),
                "peco_other": peco.get("other", False),
                "peco_max_score": peco.get("max_retrieval_score"),
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
