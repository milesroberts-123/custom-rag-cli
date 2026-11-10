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


def _review_reasons(tissue, germplasm, exposure, study, rna_type, athrdb, review):
    """Reasons a sample needs a human, based on model uncertainty only.

    ``OTHER``/``unknown`` outcomes are labeling results, not uncertainty: a
    model that confidently reports "no matching category" has told us what it
    knows about the metadata. Flagging those enqueued 94% of a window, so only
    confidence thresholds (and the AthRDB cross-check) trigger review here.
    """
    reasons = []

    confidence = rna_type.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["rna_type_confidence"]
    ):
        reasons.append("rna_type_low_confidence")

    confidence = tissue.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["tissue_confidence"]
    ):
        reasons.append("tissue_low_confidence")

    confidence = germplasm.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["germplasm_confidence"]
    ):
        reasons.append("germplasm_low_confidence")

    score = exposure.get("max_retrieval_score")
    if isinstance(score, (int, float)) and score < float(
        review["exposure_retrieval_score"]
    ):
        reasons.append("exposure_weak_retrieval")

    confidence = study.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < float(
        review["study_confidence"]
    ):
        reasons.append("study_low_confidence")

    if review.get("athrdb_crosscheck", True) and _athrdb_crosscheck(
        athrdb, tissue, germplasm
    ):
        reasons.append("athrdb_disagreement")
    return list(dict.fromkeys(reasons))


LABEL_KINDS = ("tissue", "germplasm", "exposure", "study_condition")


def _label_path(kind, samn):
    """Path to one BioSample's annotation record under results/."""
    return Path("results") / kind / f"{samn}.json"


def _athrdb_path(run):
    """AthRDB curates GEO libraries, which are keyed by run."""
    return Path("results/metadata/athrdb") / f"{run}.json"


def _mixed_run_samples(sheet):
    """BioSamples whose runs disagree on experiment title or library name."""
    groups = sheet.groupby("biosample")["run"]
    mixed = set()
    for samn, runs in groups:
        if len(runs) < 2:
            continue
        titles, names = set(), set()
        for run in runs:
            path = Path("results/metadata/sra") / f"{run}.json"
            if not path.exists():
                continue
            record = json.loads(path.read_text())
            titles.add((record.get("experiment_title") or "").strip())
            names.add((record.get("library_name") or "").strip())
        if len(titles) > 1 or len(names) > 1:
            mixed.add(samn)
    return mixed


FRAGMENT_COLUMNS = LABEL_COLUMNS + ["included", "exclusion_reason"]

# Reasons that used to flag a label value rather than model uncertainty. They
# are dropped on read so fragments written before the gating change (and any
# copied forward) produce the same table as fresh ones.
RETIRED_REASONS = frozenset(
    {
        "tissue_other",
        "germplasm_unknown",
        "exposure_other",
        "study_other",
        "no_paper",
        "paper_low_confidence",
    }
)


def _retire_reasons(value):
    """Drop retired review reasons from one fragment's ``;``-joined string."""
    reasons = [reason for reason in str(value or "").split(";") if reason]
    return ";".join(reason for reason in reasons if reason not in RETIRED_REASONS)


def build_rows(sheet, samns, review, terms, window, destination):
    """Build one window-chunk fragment: one row per run, included or excluded.

    Row construction happens here, next to the labels, so `aggregate` never has
    to reopen per-run metadata again: it only concatenates fragments. That keeps
    the final table's cost proportional to the number of chunks, not to the
    number of runs processed so far.
    """
    terms_by_id = terms
    mixed = _mixed_run_samples(sheet)
    wanted = set(samns)
    rows = []

    for sample in sheet.itertuples():
        if sample.biosample not in wanted:
            continue
        rna_type_path = _label_path("rna_type", sample.biosample)
        if not rna_type_path.exists():
            continue
        rna_type = json.loads(rna_type_path.read_text())

        base = {
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
        }

        if not rna_type.get("mrna_eligible", False):
            rows.append(
                {
                    **base,
                    "included": False,
                    "exclusion_reason": _exclusion_reason(rna_type),
                }
            )
            continue

        paths = {kind: _label_path(kind, sample.biosample) for kind in LABEL_KINDS}
        if any(not path.exists() for path in paths.values()):
            continue

        tissue = json.loads(paths["tissue"].read_text())
        germplasm = json.loads(paths["germplasm"].read_text())
        exposure = json.loads(paths["exposure"].read_text())
        study = json.loads(paths["study_condition"].read_text())

        athrdb_path = _athrdb_path(sample.run)
        athrdb = json.loads(athrdb_path.read_text()) if athrdb_path.exists() else {}

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
            if terms_by_id.get(term["term_id"], {}).get("growth_system")
        ]
        reasons = _review_reasons(
            tissue, germplasm, exposure, study, rna_type, athrdb, review
        )
        if sample.biosample in mixed:
            reasons.append("mixed_run_context")

        rows.append(
            {
                **base,
                "included": True,
                "mrna_eligible": True,
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

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=FRAGMENT_COLUMNS).to_csv(
        destination, sep="\t", index=False, na_rep=""
    )
    return len(rows)


def _fragment_order(path):
    """Sort fragments by (window, chunk) so the newest window wins dedupes."""
    stem = Path(path).stem
    window, _, chunk = stem.rpartition("-")
    try:
        return int(window), int(chunk)
    except ValueError:
        return 0, 0


def main():
    sheet = pd.read_table(snakemake.params.samples, dtype=str)
    fragments = sorted(Path("results/rows").glob("*.tsv"), key=_fragment_order)
    frames = []
    for path in fragments:
        frames.append(pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False))

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        # Later fragments (newer window) replace earlier rows for the same run.
        combined = combined.drop_duplicates(subset="run", keep="last")
        included = combined[combined["included"] == "True"].copy()
        if "review_reasons" in included:
            included["review_reasons"] = included["review_reasons"].map(_retire_reasons)
            included["review_required"] = included["review_reasons"].map(bool)
        excluded = combined[combined["included"] != "True"]
    else:
        included = pd.DataFrame(columns=FRAGMENT_COLUMNS)
        excluded = pd.DataFrame(columns=FRAGMENT_COLUMNS)

    labels = included.reindex(columns=LABEL_COLUMNS).astype(object).fillna("")
    excluded_out = excluded.reindex(columns=EXCLUDED_COLUMNS).astype(object).fillna("")

    output = Path(snakemake.output.labels)
    output.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(output, sep="\t", index=False)

    excluded_output = Path(snakemake.output.excluded)
    excluded_output.parent.mkdir(parents=True, exist_ok=True)
    excluded_out.to_csv(excluded_output, sep="\t", index=False)

    accounted = set(combined["run"]) if frames else set()
    missing = [run for run in sheet["run"] if run not in accounted]
    if missing:
        print(
            f"{len(missing)} of {len(sheet)} sheet runs have no row yet "
            f"({'; '.join(missing[:5])}"
            f"{'...' if len(missing) > 5 else ''}); rerun their window to "
            "finish them.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
