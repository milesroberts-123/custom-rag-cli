"""SQLite storage and audit log for human annotation review."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS base_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    row_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS base_annotations (
    import_id INTEGER NOT NULL,
    run TEXT NOT NULL,
    bioproject TEXT,
    biosample TEXT,
    species TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (import_id, run),
    FOREIGN KEY (import_id) REFERENCES base_imports (id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    run TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('edit', 'reviewed', 'unreviewed', 'note')
    ),
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events (run);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type);
"""

ALLOWED_EVENTS = {"edit", "reviewed", "unreviewed", "note"}


def connect(path: Path) -> sqlite3.Connection:
    """Open the review database and ensure the schema exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _encode(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def import_base(
    connection: sqlite3.Connection,
    rows: list[dict],
    source_path: Path,
    source_sha256: str,
) -> tuple[int, bool]:
    """Import a labels snapshot; return (import_id, was_imported)."""
    existing = connection.execute(
        "SELECT id FROM base_imports WHERE source_sha256 = ?", (source_sha256,)
    ).fetchone()
    if existing is not None:
        return int(existing["id"]), False

    if not rows:
        raise ValueError("cannot import an empty annotation table")
    runs = [row.get("run") for row in rows]
    if any(not run for run in runs):
        raise ValueError("every annotation row needs a run accession")
    if len(set(runs)) != len(runs):
        raise ValueError("annotation table contains duplicate run accessions")

    with connection:
        cursor = connection.execute(
            """
            INSERT INTO base_imports
                (imported_at, source_path, source_sha256, row_count)
            VALUES (?, ?, ?, ?)
            """,
            (_now(), str(source_path), source_sha256, len(rows)),
        )
        import_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO base_annotations
                (import_id, run, bioproject, biosample, species, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    import_id,
                    row["run"],
                    row.get("bioproject", ""),
                    row.get("biosample", ""),
                    row.get("species", ""),
                    json.dumps(row, sort_keys=True),
                )
                for row in rows
            ],
        )
    return import_id, True


def latest_import_id(connection: sqlite3.Connection) -> int | None:
    """Return the newest base snapshot ID."""
    row = connection.execute("SELECT MAX(id) AS id FROM base_imports").fetchone()
    return int(row["id"]) if row and row["id"] is not None else None


def base_rows(connection: sqlite3.Connection, import_id: int) -> list[dict]:
    """Return the annotation rows for a snapshot."""
    rows = connection.execute(
        """
        SELECT payload_json FROM base_annotations
        WHERE import_id = ?
        ORDER BY run
        """,
        (import_id,),
    ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def record_event(
    connection: sqlite3.Connection,
    reviewer: str,
    run: str,
    event_type: str,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    note: str | None = None,
) -> int:
    """Append an edit, review, or note event."""
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    if not run:
        raise ValueError("run is required")
    if event_type not in ALLOWED_EVENTS:
        raise ValueError(f"unsupported event type: {event_type}")
    if event_type == "edit" and not field:
        raise ValueError("edit events require a field")
    if event_type == "note" and new_value is None:
        raise ValueError("note events require text")

    import_id = latest_import_id(connection)
    if import_id is None:
        raise ValueError("no annotation snapshot has been imported")
    exists = connection.execute(
        "SELECT 1 FROM base_annotations WHERE import_id = ? AND run = ?",
        (import_id, run),
    ).fetchone()
    if exists is None:
        raise ValueError(f"unknown run accession: {run}")

    with connection:
        cursor = connection.execute(
            """
            INSERT INTO events
                (ts, reviewer, run, event_type, field, old_value, new_value, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                reviewer,
                run,
                event_type,
                field,
                _encode(old_value),
                _encode(new_value),
                note,
            ),
        )
    return int(cursor.lastrowid)


def latest_edits(connection: sqlite3.Connection) -> dict[tuple[str, str], Any]:
    """Return the latest edit value for every (run, field)."""
    rows = connection.execute(
        """
        SELECT e.run, e.field, e.new_value
        FROM events e
        JOIN (
            SELECT run, field, MAX(id) AS id
            FROM events
            WHERE event_type = 'edit'
            GROUP BY run, field
        ) latest ON e.id = latest.id
        """
    ).fetchall()
    return {(row["run"], row["field"]): _decode(row["new_value"]) for row in rows}


def review_status(connection: sqlite3.Connection) -> dict[str, dict]:
    """Return the latest review status per run."""
    rows = connection.execute(
        """
        SELECT e.run, e.event_type, e.reviewer, e.ts, e.id
        FROM events e
        JOIN (
            SELECT run, MAX(id) AS id
            FROM events
            WHERE event_type IN ('reviewed', 'unreviewed')
            GROUP BY run
        ) latest ON e.id = latest.id
        """
    ).fetchall()
    return {row["run"]: dict(row) for row in rows}


def latest_notes(connection: sqlite3.Connection) -> dict[str, str]:
    """Return the latest note text per run."""
    rows = connection.execute(
        """
        SELECT e.run, e.new_value
        FROM events e
        JOIN (
            SELECT run, MAX(id) AS id
            FROM events
            WHERE event_type = 'note'
            GROUP BY run
        ) latest ON e.id = latest.id
        """
    ).fetchall()
    return {row["run"]: _decode(row["new_value"]) or "" for row in rows}


def latest_note(connection: sqlite3.Connection, run: str) -> str:
    """Return the latest note for one run."""
    row = connection.execute(
        """
        SELECT new_value FROM events
        WHERE run = ? AND event_type = 'note'
        ORDER BY id DESC LIMIT 1
        """,
        (run,),
    ).fetchone()
    return (_decode(row["new_value"]) if row else "") or ""


def event_history(connection: sqlite3.Connection, run: str) -> list[dict]:
    """Return the audit history for one run, newest first."""
    rows = connection.execute(
        """
        SELECT id, ts, reviewer, event_type, field, old_value, new_value, note
        FROM events WHERE run = ? ORDER BY id DESC
        """,
        (run,),
    ).fetchall()
    history = []
    for row in rows:
        record = dict(row)
        record["old_value"] = _decode(record["old_value"])
        record["new_value"] = _decode(record["new_value"])
        history.append(record)
    return history


def last_edit(connection: sqlite3.Connection, run: str) -> dict | None:
    """Return the latest edit for a run, if any."""
    row = connection.execute(
        """
        SELECT id, ts, reviewer, field, old_value, new_value
        FROM events WHERE run = ? AND event_type = 'edit'
        ORDER BY id DESC LIMIT 1
        """,
        (run,),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["old_value"] = _decode(record["old_value"])
    record["new_value"] = _decode(record["new_value"])
    return record


def compare_imports(
    connection: sqlite3.Connection, old_id: int, new_id: int
) -> dict[str, list[str]]:
    """Compare two base snapshots by run and payload."""
    old_rows = {
        row["run"]: row["payload_json"]
        for row in connection.execute(
            "SELECT run, payload_json FROM base_annotations WHERE import_id = ?",
            (old_id,),
        )
    }
    new_rows = {
        row["run"]: row["payload_json"]
        for row in connection.execute(
            "SELECT run, payload_json FROM base_annotations WHERE import_id = ?",
            (new_id,),
        )
    }
    old_runs = set(old_rows)
    new_runs = set(new_rows)
    return {
        "added": sorted(new_runs - old_runs),
        "removed": sorted(old_runs - new_runs),
        "changed": sorted(
            run for run in old_runs & new_runs if old_rows[run] != new_rows[run]
        ),
    }


def orphan_runs(connection: sqlite3.Connection, import_id: int) -> list[str]:
    """Return event runs that are absent from the latest snapshot."""
    rows = connection.execute(
        """
        SELECT DISTINCT e.run
        FROM events e
        LEFT JOIN base_annotations b
            ON b.run = e.run AND b.import_id = ?
        WHERE b.run IS NULL
        ORDER BY e.run
        """,
        (import_id,),
    ).fetchall()
    return [row["run"] for row in rows]


def counts(connection: sqlite3.Connection, import_id: int) -> dict:
    """Return reviewed and remaining counts, globally and by project."""
    base = connection.execute(
        "SELECT run, bioproject FROM base_annotations WHERE import_id = ?",
        (import_id,),
    ).fetchall()
    statuses = review_status(connection)
    reviewed = {
        row["run"]
        for row in base
        if statuses.get(row["run"], {}).get("event_type") == "reviewed"
    }
    projects: dict[str, dict[str, int]] = {}
    for row in base:
        project = row["bioproject"] or ""
        project_counts = projects.setdefault(
            project, {"total": 0, "reviewed": 0, "remaining": 0}
        )
        project_counts["total"] += 1
        if row["run"] in reviewed:
            project_counts["reviewed"] += 1
    for project_counts in projects.values():
        project_counts["remaining"] = (
            project_counts["total"] - project_counts["reviewed"]
        )
    total = len(base)
    return {
        "total": total,
        "reviewed": len(reviewed),
        "remaining": total - len(reviewed),
        "projects": projects,
    }
