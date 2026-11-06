"""Build the quantification target list from labels.tsv and SRA metadata.

Writes ``results/quant/targets.tsv`` (one row per BioSample) and
``results/quant/skipped.tsv`` (runs that cannot be quantified).

The Snakefile reads the target list at parse time, which is why this is a
separate preparation step rather than a rule: the DAG's shape (pooled vs
per-run Salmon, single- vs paired-end file names) depends on library layout,
and layout live only in per-run metadata files.

Layout is read from ``resources/SraRunInfo.csv`` when present (one row per run,
column ``LibraryLayout``), otherwise from the per-run SRA metadata JSONs.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ELIGIBLE_VALUES = {"true", "1", "yes", "y"}


def read_labels(path):
    """Return {run: row} for mRNA-eligible runs."""
    rows = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = (row.get("mrna_eligible") or "").strip().lower()
            if value in ELIGIBLE_VALUES:
                rows[row["run"]] = row
    return rows


def read_layout_from_csv(path):
    """Return {run: SINGLE|PAIRED} from an SRA RunInfo table."""
    layout = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            run = (row.get("Run") or "").strip()
            value = (row.get("LibraryLayout") or "").strip().upper()
            if run and value in {"SINGLE", "PAIRED"}:
                layout[run] = value
    return layout


def read_layout_from_metadata(directory):
    """Return {run: SINGLE|PAIRED} from per-run SRA metadata JSONs."""
    layout = {}
    for path in Path(directory).glob("*.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        value = (record.get("library_layout") or "").strip().upper()
        if value in {"SINGLE", "PAIRED"}:
            layout[record.get("run") or path.stem] = value
    return layout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default="results/labels.tsv")
    parser.add_argument("--runinfo", default="resources/SraRunInfo.csv")
    parser.add_argument("--sra-dir", default="results/metadata/sra")
    parser.add_argument("--output", default="results/quant/targets.tsv")
    parser.add_argument("--skipped", default="results/quant/skipped.tsv")
    parser.add_argument("--bioprojects", nargs="*", default=[])
    parser.add_argument("--max-targets", type=int, default=0)
    parser.add_argument("--one-run-per-biosample", action="store_true")
    args = parser.parse_args(argv)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    skipped_path = Path(args.skipped)
    skipped_path.parent.mkdir(parents=True, exist_ok=True)

    if not Path(args.labels).exists():
        print(
            f"{args.labels} not found; write an empty target list and stop. "
            "Run the labeling workflow first.",
            file=sys.stderr,
        )
        output.write_text(
            "biosample\tmode\tlayout\tn_runs\truns\trun_layouts\tbioproject\tspecies\n"
        )
        skipped_path.write_text("run\treason\n")
        return 0

    labels = read_labels(args.labels)
    layout = (
        read_layout_from_csv(args.runinfo)
        if Path(args.runinfo).exists()
        else read_layout_from_metadata(args.sra_dir)
    )
    allow = set(args.bioprojects)

    groups = {}
    skipped = []
    for run, row in labels.items():
        samn = row.get("biosample") or ""
        prjna = row.get("bioproject") or ""
        species = row.get("species") or ""
        if allow and prjna not in allow:
            skipped.append((run, "not_in_requested_bioprojects"))
            continue
        run_layout = layout.get(run, "")
        if not run_layout:
            skipped.append((run, "unknown_library_layout"))
            continue
        group = groups.setdefault(
            samn,
            {"runs": [], "layouts": set(), "bioproject": prjna, "species": species},
        )
        group["runs"].append(run)
        group["layouts"].add(run_layout)

    rows = []
    for samn, group in groups.items():
        runs = group["runs"]
        if args.one_run_per_biosample:
            runs = runs[:1]
        layouts = {layout[run] for run in runs}
        mode = "pool" if len(layouts) == 1 else "per_run"
        for run in group["runs"]:
            if run not in runs:
                skipped.append((run, "one_run_per_biosample"))
        rows.append(
            {
                "biosample": samn,
                "mode": mode,
                "layout": sorted(layouts)[0] if len(layouts) == 1 else "MIXED",
                "n_runs": len(runs),
                "runs": ",".join(runs),
                "run_layouts": ",".join(layout[run] for run in runs),
                "bioproject": group["bioproject"],
                "species": group["species"],
            }
        )

    rows.sort(key=lambda row: row["biosample"])
    if args.max_targets > 0:
        rows = rows[: args.max_targets]

    with open(output, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "biosample",
                "mode",
                "layout",
                "n_runs",
                "runs",
                "run_layouts",
                "bioproject",
                "species",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    with open(skipped_path, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["run", "reason"])
        writer.writerows(sorted(skipped))

    pooled = sum(1 for row in rows if row["mode"] == "pool")
    print(
        f"wrote {len(rows)} targets ({pooled} pooled, "
        f"{len(rows) - pooled} per-run) and {len(skipped)} skipped runs",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
