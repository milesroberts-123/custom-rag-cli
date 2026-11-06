"""Tests for the chunk resume/fail-soft helper."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from chunk_runner import run_chunk

LOGGER = logging.getLogger("test_chunk")


def test_run_chunk_skips_existing_and_stubs_failures(tmp_path):
    existing = tmp_path / "done.json"
    existing.write_text("{}\n")
    marker = tmp_path / "0.done"

    def output_for(item):
        return tmp_path / f"{item}.json"

    def process(item):
        if item == "bad":
            raise RuntimeError("model output invalid")
        Path(output_for(item)).write_text("{}\n")

    def stub(item, error):
        return {"samn": item, "error": error}

    failures = run_chunk(
        ["done", "good", "bad"], output_for, process, stub, marker, LOGGER
    )

    assert failures == 1
    assert json.loads(marker.read_text()) == {
        "samples": 3,
        "written": 1,
        "skipped": 1,
        "failures": 1,
    }
    assert json.loads((tmp_path / "bad.json").read_text())["error"] == (
        "model output invalid"
    )
