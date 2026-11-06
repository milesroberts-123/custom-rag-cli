"""Resume and fail-soft helpers for the chunked labeling rules.

A chunk job handles ``label_chunk_size`` BioSamples. Two properties matter:

* Resuming: a retried chunk must not redo samples whose output already exists,
  otherwise one bad sample costs a whole chunk of GPU time.
* Fail-soft: a single sample that the model cannot label must not fail the
  chunk (and with it the window). The sample gets a reviewable stub instead,
  and the marker records how many samples failed so the DAG shows it.
"""

import json
from pathlib import Path


def run_chunk(items, output_for, process, stub_for, marker_path, logger):
    """Process ``items``, skipping existing outputs, stubbing failures.

    ``output_for(item)`` returns the per-sample output path, ``process(item)``
    does the work and writes it, and ``stub_for(item, error)`` builds the
    review stub written when ``process`` raises. Returns the failure count.
    """
    written = 0
    skipped = 0
    failures = 0
    for item in items:
        output = Path(output_for(item))
        if output.exists():
            skipped += 1
            continue
        try:
            process(item)
        except Exception as error:  # noqa: BLE001 - one sample must not fail the chunk
            failures += 1
            logger.warning(
                "%s: labeling failed (%s); writing a review stub", item, error
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(stub_for(item, str(error)), indent=2, sort_keys=True) + "\n"
            )
        else:
            written += 1

    marker = Path(marker_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "samples": len(items),
                "written": written,
                "skipped": skipped,
                "failures": failures,
            }
        )
        + "\n"
    )
    logger.info(
        "chunk done: %d written, %d skipped, %d failed", written, skipped, failures
    )
    return failures
