"""Tests for replaying review events into the reviewed table."""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from review_app import db, export, loaders


def test_build_reviewed_rows_applies_edits(base_rows, terms):
    edits = {
        ("SRR000001", "tissue"): "root",
        ("SRR000001", "germplasm_type"): "mutant",
        ("SRR000001", "peco_exposure_ids"): "PECO:0000001;PECO:0000002",
        ("SRR000001", "peco_study_id"): "PECO:0000004",
        ("SRR000001", "peco_exposure_other"): True,
    }
    statuses = {
        "SRR000001": {
            "event_type": "reviewed",
            "reviewer": "miles",
            "ts": "2026-11-02T12:00:00+00:00",
        }
    }
    rows = export.build_reviewed_rows(
        base_rows, edits, statuses, {"SRR000001": "checked figures"}, terms
    )
    first = rows[0]
    assert first["tissue"] == "root"
    assert first["tissue_source"] == "human"
    assert first["tissue_confidence"] == ""
    assert first["germplasm_type"] == "mutant"
    assert first["is_natural_accession"] is False
    assert first["germplasm_confidence"] == ""
    assert first["germplasm_evidence"] == "human review"
    assert first["peco_exposure_ids"] == "PECO:0000001;PECO:0000002"
    assert first["peco_exposure_labels"] == "cold exposure;agar medium"
    assert first["peco_exposure_other"] is True
    assert first["peco_exposure_max_score"] == ""
    assert first["peco_study_id"] == "PECO:0000004"
    assert first["peco_study_label"] == "field study"
    assert first["peco_study_confidence"] == ""
    assert first["growth_system_ids"] == "PECO:0000002"
    assert first["growth_system_labels"] == "agar medium"
    assert first["model_tissue"] == "leaf"
    assert first["model_germplasm_type"] == "natural_accession"
    assert first["model_peco_exposure_ids"] == "PECO:0000001;PECO:0000002"
    assert first["model_peco_study_id"] == "PECO:0000003"
    assert first["model_review_required"] == "True"
    assert first["model_review_reasons"] == "tissue_other"
    assert first["review_reasons"] == "tissue_other"
    assert first["review_status"] == "reviewed"
    assert first["reviewed"] is True
    assert first["reviewed_by"] == "miles"
    assert first["reviewed_at"] == "2026-11-02T12:00:00+00:00"
    assert first["review_notes"] == "checked figures"
    assert first["review_required"] is False

    second = rows[1]
    assert second["tissue"] == "root"
    assert second["review_status"] == "pending"
    assert second["reviewed"] is False
    assert second["review_required"] is True


def test_build_reviewed_rows_keeps_base_values_without_edits(base_rows, terms):
    rows = export.build_reviewed_rows(base_rows, {}, {}, {}, terms)
    assert rows[0]["tissue"] == "leaf"
    assert rows[0]["is_natural_accession"] is True
    assert rows[0]["growth_system_ids"] == "PECO:0000002"
    assert rows[1]["review_required"] is True


def test_export_integration(review_root):
    labels_path = review_root / "results" / "labels.tsv"
    rows = loaders.load_labels(labels_path).to_dict("records")
    source_sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    db_path = review_root / "results" / "review" / "review.db"
    connection = db.connect(db_path)
    try:
        import_id, _ = db.import_base(connection, rows, labels_path, source_sha)
        db.record_event(
            connection,
            "miles",
            "SRR000001",
            "edit",
            field="tissue",
            old_value="leaf",
            new_value="root",
        )
        db.record_event(connection, "miles", "SRR000001", "reviewed")
        assert import_id > 0
    finally:
        connection.close()

    csv_path = review_root / "results" / "labels.reviewed.csv"
    result = export.export_reviewed(
        root=review_root,
        db_path=db_path,
        csv_path=csv_path,
    )
    assert result["rows"] == 3
    frame = pd.read_csv(csv_path)
    first = frame[frame["run"] == "SRR000001"].iloc[0]
    assert first["tissue"] == "root"
    assert first["tissue_source"] == "human"
    assert bool(first["reviewed"])
    assert first["review_status"] == "reviewed"
    assert first["model_tissue"] == "leaf"
    assert (review_root / "results" / "labels.reviewed.tsv").exists()


def test_export_without_import_raises(review_root):
    with pytest.raises(RuntimeError, match="no annotation snapshot"):
        export.export_reviewed(root=review_root)


def test_write_table_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        export.write_table([], tmp_path / "labels.csv", ",")
