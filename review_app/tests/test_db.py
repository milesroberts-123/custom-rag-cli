"""Tests for the SQLite review store."""

from __future__ import annotations

import hashlib

import pytest

from review_app import db


def _import(connection, rows, name="labels.tsv"):
    payload = "\n".join(str(row) for row in rows).encode()
    return db.import_base(
        connection,
        rows,
        name,
        hashlib.sha256(payload).hexdigest(),
    )


def test_import_reuses_snapshot(review_db, base_rows):
    first_id, imported = _import(review_db, base_rows)
    assert imported is True
    second_id, imported_again = _import(review_db, base_rows)
    assert imported_again is False
    assert second_id == first_id
    assert len(db.base_rows(review_db, first_id)) == len(base_rows)


def test_import_changed_snapshot_creates_new_import(review_db, base_rows):
    first_id, _ = _import(review_db, base_rows)
    changed = [dict(row) for row in base_rows]
    changed[0]["tissue"] = "root"
    second_id, imported = _import(review_db, changed, name="labels-v2.tsv")
    assert imported is True
    assert second_id != first_id
    changes = db.compare_imports(review_db, first_id, second_id)
    assert changes["changed"] == ["SRR000001"]
    assert changes["added"] == []
    assert changes["removed"] == []


def test_edits_and_review_counts(review_db, base_rows):
    import_id, _ = _import(review_db, base_rows)
    db.record_event(
        review_db,
        "miles",
        "SRR000001",
        "edit",
        field="tissue",
        old_value="leaf",
        new_value="root",
    )
    edits = db.latest_edits(review_db)
    assert edits[("SRR000001", "tissue")] == "root"
    assert db.counts(review_db, import_id) == {
        "total": 3,
        "reviewed": 0,
        "remaining": 3,
        "projects": {
            "PRJNA000001": {"total": 2, "reviewed": 0, "remaining": 2},
            "PRJNA000002": {"total": 1, "reviewed": 0, "remaining": 1},
        },
    }

    db.record_event(review_db, "miles", "SRR000001", "reviewed")
    assert db.review_status(review_db)["SRR000001"]["event_type"] == "reviewed"
    counts = db.counts(review_db, import_id)
    assert counts["reviewed"] == 1
    assert counts["remaining"] == 2

    db.record_event(review_db, "miles", "SRR000001", "unreviewed")
    assert db.counts(review_db, import_id)["reviewed"] == 0


def test_history_last_edit_and_notes(review_db, base_rows):
    _import(review_db, base_rows)
    db.record_event(
        review_db,
        "miles",
        "SRR000001",
        "edit",
        field="tissue",
        old_value="leaf",
        new_value="root",
    )
    db.record_event(
        review_db,
        "miles",
        "SRR000001",
        "note",
        field="notes",
        new_value="looked at figures",
    )
    last = db.last_edit(review_db, "SRR000001")
    assert last["field"] == "tissue"
    assert last["old_value"] == "leaf"
    assert last["new_value"] == "root"
    assert db.latest_note(review_db, "SRR000001") == "looked at figures"
    history = db.event_history(review_db, "SRR000001")
    assert [row["event_type"] for row in history] == ["note", "edit"]


def test_event_validation(review_db, base_rows):
    _import(review_db, base_rows)
    with pytest.raises(ValueError, match="reviewer"):
        db.record_event(review_db, "", "SRR000001", "reviewed")
    with pytest.raises(ValueError, match="unknown run"):
        db.record_event(review_db, "miles", "SRR999999", "reviewed")
    with pytest.raises(ValueError, match="field"):
        db.record_event(review_db, "miles", "SRR000001", "edit")


def test_orphan_runs(review_db, base_rows):
    first_id, _ = _import(review_db, base_rows)
    db.record_event(review_db, "miles", "SRR000001", "reviewed")
    new_rows = [row for row in base_rows if row["run"] != "SRR000001"]
    second_id, _ = _import(review_db, new_rows, name="labels-v2.tsv")
    assert db.orphan_runs(review_db, second_id) == ["SRR000001"]
    assert db.orphan_runs(review_db, first_id) == []
