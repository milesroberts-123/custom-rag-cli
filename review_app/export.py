"""Replay review events and write the human-reviewed annotation table."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from review_app import db, loaders


def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _term_label(term_id: str, terms_by_id: dict[str, dict]) -> str:
    if not term_id:
        return ""
    return terms_by_id.get(term_id, {}).get("label", term_id)


def build_reviewed_rows(
    base_rows: list[dict],
    edits: dict[tuple[str, str], Any],
    statuses: dict[str, dict],
    notes: dict[str, str],
    terms: list[dict],
) -> list[dict]:
    """Apply edits and review status to the base annotation rows."""
    terms_by_id = {term["id"]: term for term in terms}
    rows = []
    for base in base_rows:
        run = base["run"]
        row = dict(base)
        status = statuses.get(run, {})
        reviewed = status.get("event_type") == "reviewed"

        tissue = edits.get((run, "tissue"), base.get("tissue") or "")
        germplasm = edits.get((run, "germplasm_type"), base.get("germplasm_type") or "")
        exposure_ids = _split_ids(
            edits.get((run, "peco_exposure_ids"), base.get("peco_exposure_ids") or "")
        )
        exposure_other = _as_bool(
            edits.get(
                (run, "peco_exposure_other"),
                base.get("peco_exposure_other"),
            )
        )
        no_condition = _as_bool(
            edits.get(
                (run, "peco_exposure_no_condition"),
                base.get("peco_exposure_no_condition"),
            )
        )
        suggested_label = (
            edits.get(
                (run, "peco_exposure_suggested_label"),
                base.get("peco_exposure_suggested_label") or "",
            )
            or ""
        )
        study_id = edits.get((run, "peco_study_id"), base.get("peco_study_id") or "")
        growth_ids = [
            term_id
            for term_id in exposure_ids
            if terms_by_id.get(term_id, {}).get("growth_system")
        ]

        row["tissue"] = tissue
        row["tissue_source"] = (
            "human" if (run, "tissue") in edits else base.get("tissue_source", "")
        )
        if (run, "tissue") in edits:
            row["tissue_confidence"] = ""
        row["germplasm_type"] = germplasm
        row["is_natural_accession"] = germplasm == "natural_accession"
        if (run, "germplasm_type") in edits:
            row["germplasm_confidence"] = ""
            row["germplasm_evidence"] = "human review"
        row["peco_exposure_ids"] = ";".join(exposure_ids)
        row["peco_exposure_labels"] = ";".join(
            _term_label(term_id, terms_by_id) for term_id in exposure_ids
        )
        row["peco_exposure_other"] = exposure_other
        row["peco_exposure_no_condition"] = no_condition
        row["peco_exposure_suggested_label"] = suggested_label
        if (run, "peco_exposure_ids") in edits:
            row["peco_exposure_evidence"] = "human review"
            row["peco_exposure_max_score"] = ""
        row["peco_study_id"] = study_id
        row["peco_study_label"] = _term_label(study_id, terms_by_id)
        if (run, "peco_study_id") in edits:
            row["peco_study_confidence"] = ""
        row["growth_system_ids"] = ";".join(growth_ids)
        row["growth_system_labels"] = ";".join(
            _term_label(term_id, terms_by_id) for term_id in growth_ids
        )

        row["model_tissue"] = base.get("tissue")
        row["model_germplasm_type"] = base.get("germplasm_type")
        row["model_peco_exposure_ids"] = base.get("peco_exposure_ids")
        row["model_peco_study_id"] = base.get("peco_study_id")
        row["model_review_required"] = base.get("review_required")
        row["model_review_reasons"] = base.get("review_reasons")

        row["review_status"] = "reviewed" if reviewed else "pending"
        row["reviewed"] = reviewed
        row["reviewed_by"] = status.get("reviewer", "") if reviewed else ""
        row["reviewed_at"] = status.get("ts", "") if reviewed else ""
        row["review_notes"] = notes.get(run, "")
        row["review_required"] = _as_bool(base.get("review_required")) and not reviewed
        row["review_reasons"] = base.get("review_reasons", "")
        rows.append(row)
    return rows


def write_table(rows: list[dict], path: Path, delimiter: str) -> Path:
    """Write rows atomically as a delimited table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("cannot export an empty annotation table")
    fieldnames = list(rows[0].keys())
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)
    return path


def export_reviewed(
    root: Path = loaders.REPO_ROOT,
    db_path: Path | None = None,
    csv_path: Path | None = None,
    tsv_path: Path | None = None,
    write_tsv: bool = True,
) -> dict:
    """Export the reviewed table from SQLite."""
    root = Path(root)
    db_path = Path(db_path or root / "results" / "review" / "review.db")
    csv_path = Path(csv_path or root / "results" / "labels.reviewed.csv")
    if write_tsv:
        tsv_path = Path(tsv_path or root / "results" / "labels.reviewed.tsv")

    connection = db.connect(db_path)
    try:
        import_id = db.latest_import_id(connection)
        if import_id is None:
            raise RuntimeError(
                "no annotation snapshot imported yet; open the review app first"
            )
        rows = build_reviewed_rows(
            db.base_rows(connection, import_id),
            db.latest_edits(connection),
            db.review_status(connection),
            db.latest_notes(connection),
            loaders.load_terms(root / "resources" / "peco_index"),
        )
    finally:
        connection.close()

    written = {
        "rows": len(rows),
        "csv": write_table(rows, csv_path, ","),
        "tsv": None,
    }
    if write_tsv:
        written["tsv"] = write_table(rows, tsv_path, "\t")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=loaders.REPO_ROOT,
        help="repository root containing results/ and resources/",
    )
    parser.add_argument("--db", type=Path, default=None, help="review SQLite database")
    parser.add_argument("--csv", type=Path, default=None, help="reviewed CSV path")
    parser.add_argument("--tsv", type=Path, default=None, help="reviewed TSV path")
    parser.add_argument(
        "--no-tsv",
        action="store_true",
        help="write only the CSV output",
    )
    args = parser.parse_args(argv)
    result = export_reviewed(
        root=args.root,
        db_path=args.db,
        csv_path=args.csv,
        tsv_path=args.tsv,
        write_tsv=not args.no_tsv,
    )
    print(f"Wrote {result['rows']} rows to {result['csv']}")
    if result["tsv"] is not None:
        print(f"Wrote {result['rows']} rows to {result['tsv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
