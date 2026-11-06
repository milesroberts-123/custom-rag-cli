"""Merge per-BioSample Salmon quantification into gene-level matrices.

Because runs of a BioSample are quantified together, one ``quant.genes.sf``
already represents the sample and its TPM column is directly comparable; no
count summation or TPM recomputation is needed. The exception is a sample whose
runs differ in library layout: those are quantified separately and their counts
summed here, with TPM recomputed from the summed counts and gene lengths.
"""

import csv
import json
from pathlib import Path


def read_targets(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_quant_genes(path):
    """Return {gene: (length, effective_length, tpm, num_reads)}."""
    genes = {}
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            name = row["Name"]
            genes[name] = (
                float(row["Length"]),
                float(row["EffectiveLength"]),
                float(row["TPM"]),
                float(row["NumReads"]),
            )
    return genes


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {}


def _sum_runs(paths):
    """Sum NumReads across per-run quantifications, then recompute TPM."""
    totals = {}
    for path in paths:
        for gene, (length, _eff, _tpm, reads) in read_quant_genes(path).items():
            length_sum, reads_sum = totals.get(gene, (length, 0.0))
            totals[gene] = (length_sum, reads_sum + reads)
    rates = {
        gene: (reads / length if length else 0.0)
        for gene, (length, reads) in totals.items()
    }
    scale = sum(rates.values())
    return {
        gene: (
            totals[gene][0],
            0.0,
            (rate / scale * 1e6) if scale else 0.0,
            totals[gene][1],
        )
        for gene, rate in rates.items()
    }


def _salmon_meta(directory):
    directory = Path(directory)
    meta = read_json(directory / "aux_info" / "meta_info.json")
    counts = read_json(directory / "lib_format_counts.json")
    return {
        "num_processed": meta.get("num_processed"),
        "num_mapped": meta.get("num_mapped"),
        "percent_mapped": meta.get("percent_mapped"),
        "expected_format": counts.get("expected_format"),
        "libtype": meta.get("library_types", [None])[0]
        if isinstance(meta.get("library_types"), list) and meta.get("library_types")
        else meta.get("library_type"),
    }


def main():
    targets = read_targets(snakemake.input.targets)
    salmon_dirs = {Path(p).name: Path(p) for p in snakemake.input.salmon_dirs}
    run_dirs = {Path(p).name: Path(p) for p in snakemake.input.run_dirs}
    tin = {}
    for path in list(snakemake.input.tin) + list(snakemake.input.tin_run):
        tin[Path(path).stem] = read_json(path)
    fastp = {}
    layout = {}
    for path in list(snakemake.input.fastp_se) + list(snakemake.input.fastp_pe):
        record = read_json(path)
        run = Path(path).name.replace(".fastp.json", "")
        fastp[run] = record
    for path in snakemake.input.sra:
        record = read_json(path)
        layout[record.get("run") or Path(path).stem] = record

    columns = []
    counts = {}
    tpms = {}
    qc = []

    for target in targets:
        samn = target["biosample"]
        runs = [run for run in target["runs"].split(",") if run]
        mode = target["mode"]

        if mode == "pool":
            quant = salmon_dirs.get(samn, Path("missing")) / "quant.genes.sf"
            if not quant.exists():
                continue
            genes = read_quant_genes(quant)
            meta = _salmon_meta(salmon_dirs[samn])
            tin_record = tin.get(samn, {})
            source_dir = salmon_dirs[samn]
        else:
            paths = [
                run_dirs[run] / "quant.genes.sf"
                for run in runs
                if run in run_dirs and (run_dirs[run] / "quant.genes.sf").exists()
            ]
            if not paths:
                continue
            genes = _sum_runs(paths)
            metas = [_salmon_meta(run_dirs[run]) for run in runs if run in run_dirs]
            processed = sum(meta.get("num_processed") or 0 for meta in metas)
            mapped = sum(meta.get("num_mapped") or 0 for meta in metas)
            meta = {
                "num_processed": processed,
                "num_mapped": mapped,
                "percent_mapped": round(100 * mapped / processed, 2)
                if processed
                else None,
                "expected_format": ";".join(
                    sorted(
                        {m["expected_format"] for m in metas if m["expected_format"]}
                    )
                ),
                "libtype": ";".join(
                    sorted({m["libtype"] for m in metas if m["libtype"]})
                ),
            }
            tin_record = {
                "medTIN": _median(
                    [
                        tin[run]["medTIN"]
                        for run in runs
                        if run in tin and tin[run].get("medTIN") is not None
                    ]
                )
            }
            source_dir = run_dirs.get(runs[0], Path("missing"))

        columns.append(samn)
        for gene, (_length, _eff, tpm, reads) in genes.items():
            counts.setdefault(gene, {})[samn] = reads
            tpms.setdefault(gene, {})[samn] = tpm

        run_qc = []
        for run in runs:
            record = fastp.get(run, {})
            summary = record.get("summary", {})
            before = summary.get("before_filtering", {})
            after = summary.get("after_filtering", {})
            run_qc.append(
                {
                    "run": run,
                    "layout": (layout.get(run, {}) or {}).get("library_layout", ""),
                    "reads_before": before.get("total_reads"),
                    "reads_after": after.get("total_reads"),
                    "q30_after": after.get("q30_rate"),
                    "duplication_rate": (record.get("duplication") or {}).get("rate"),
                }
            )

        qc.append(
            {
                "biosample": samn,
                "bioproject": target["bioproject"],
                "species": target["species"],
                "mode": mode,
                "layout": target["layout"],
                "n_runs": len(runs),
                "runs": ",".join(runs),
                "num_processed": meta.get("num_processed"),
                "num_mapped": meta.get("num_mapped"),
                "percent_mapped": meta.get("percent_mapped"),
                "expected_format": meta.get("expected_format"),
                "libtype": meta.get("libtype"),
                "medTIN": tin_record.get("medTIN"),
                "tin_transcripts": tin_record.get("n_transcripts"),
                "median_skew": tin_record.get("median_skew"),
                "quant_dir": str(source_dir),
                "run_qc": run_qc,
            }
        )

    _write_matrix(snakemake.output.counts, counts, columns)
    _write_matrix(snakemake.output.tpm, tpms, columns)
    _write_qc(snakemake.output.qc, qc)

    LOGGER.info("merged %d samples, %d genes", len(columns), len(counts))


def _median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    middle = len(values) // 2
    return round(
        values[middle]
        if len(values) % 2
        else (values[middle - 1] + values[middle]) / 2,
        4,
    )


def _write_matrix(path, table, columns):
    genes = sorted(table)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["gene"] + columns)
        for gene in genes:
            writer.writerow(
                [gene] + [f"{table[gene].get(sample, 0.0):.6g}" for sample in columns]
            )


def _write_qc(path, rows):
    fields = [
        "biosample",
        "bioproject",
        "species",
        "mode",
        "layout",
        "n_runs",
        "runs",
        "num_processed",
        "num_mapped",
        "percent_mapped",
        "expected_format",
        "libtype",
        "medTIN",
        "tin_transcripts",
        "median_skew",
        "quant_dir",
        "run_qc",
    ]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            row = dict(row)
            row["run_qc"] = json.dumps(row["run_qc"])
            writer.writerow(row)


from script_logging import setup as _setup

LOGGER = _setup("merge_quant")


if __name__ == "__main__":
    main()
