"""Tests for the quantification subworkflow helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_gentrome
import compute_tin
import merge_quant
import quant_prepare
import tx2gene


def test_quant_prepare_pools_single_layout_and_splits_mixed(tmp_path):
    labels = tmp_path / "labels.tsv"
    labels.write_text(
        "run\tbiosample\tbioproject\tspecies\tmrna_eligible\n"
        "R1\tS1\tP1\tA\tTrue\n"
        "R2\tS1\tP1\tA\tTrue\n"
        "R3\tS2\tP1\tA\tTrue\n"
        "R4\tS2\tP1\tA\tTrue\n"
        "R5\tS3\tP1\tA\tFalse\n"
    )
    runinfo = tmp_path / "runinfo.csv"
    runinfo.write_text(
        "Run,LibraryLayout\nR1,SINGLE\nR2,SINGLE\nR3,SINGLE\nR4,PAIRED\nR5,SINGLE\n"
    )
    output = tmp_path / "targets.tsv"
    skipped = tmp_path / "skipped.tsv"

    quant_prepare.main(
        [
            "--labels",
            str(labels),
            "--runinfo",
            str(runinfo),
            "--output",
            str(output),
            "--skipped",
            str(skipped),
        ]
    )

    rows = [line.rstrip("\n").split("\t") for line in output.read_text().splitlines()]
    header, rows = rows[0], rows[1:]
    assert header[:6] == [
        "biosample",
        "mode",
        "layout",
        "n_runs",
        "runs",
        "run_layouts",
    ]
    by_sample = {row[0]: row for row in rows}
    assert by_sample["S1"][1] == "pool"
    assert by_sample["S1"][2] == "SINGLE"
    assert by_sample["S2"][1] == "per_run"
    assert by_sample["S2"][2] == "MIXED"
    assert "S3" not in by_sample  # not mRNA-eligible


def test_quant_prepare_handles_missing_labels(tmp_path):
    output = tmp_path / "targets.tsv"
    skipped = tmp_path / "skipped.tsv"
    quant_prepare.main(
        [
            "--labels",
            str(tmp_path / "absent.tsv"),
            "--output",
            str(output),
            "--skipped",
            str(skipped),
        ]
    )
    assert output.read_text().startswith("biosample\tmode\tlayout")
    assert skipped.read_text().strip() == "run\treason"


def test_build_gentrome_appends_genome_and_lists_decoys(tmp_path):
    cdna = tmp_path / "cdna.fa"
    cdna.write_text(">AT1G00010.1\nACGT\n")
    genome = tmp_path / "genome.fa"
    genome.write_text(">Chr1\nAAAA\n>Chr2\nCCCC\n")
    gentrome = tmp_path / "gentrome.fa"

    with open(gentrome, "w") as out:
        build_gentrome._copy(cdna, out)
        names = build_gentrome._copy(genome, out)

    assert names == ["Chr1", "Chr2"]
    text = gentrome.read_text()
    assert text.startswith(">AT1G00010.1")
    assert ">Chr1" in text and text.index(">Chr1") > text.index(">AT1G00010.1")


def test_tx2gene_parses_transcript_rows(tmp_path):
    gtf = tmp_path / "a.gtf"
    gtf.write_text(
        "Chr1\tsrc\ttranscript\t1\t100\t.\t+\t.\t"
        'gene_id "AT1G00010"; transcript_id "AT1G00010.1"; gene_name "ABC";\n'
        'Chr1\tsrc\texon\t1\t50\t.\t+\t.\tgene_id "AT1G00010"; '
        'transcript_id "AT1G00010.1";\n'
    )
    rows = list(tx2gene.parse_gtf(gtf))
    assert rows == [("AT1G00010.1", "AT1G00010", "ABC")]


def test_tin_is_hundred_when_flat_and_low_when_degraded():
    flat = [5] * 100
    assert compute_tin._tin(flat) == 100.0

    degraded = [0] * 90 + [10] * 10
    assert compute_tin._tin(degraded) < 20

    assert compute_tin._tin([]) == 0.0


def test_skew_reports_3_prime_depletion():
    degraded = [10] * 10 + [0] * 90
    skew = compute_tin._skew(degraded)
    assert skew is not None and skew > 0  # 5' richer than 3'


def test_sum_runs_recomputes_tpm_from_summed_counts(tmp_path):
    def write(path, rows):
        path.write_text(
            "Name\tLength\tEffectiveLength\tTPM\tNumReads\n"
            + "".join(
                f"{name}\t{length}\t{length}\t{tpm}\t{reads}\n"
                for name, length, tpm, reads in rows
            )
        )

    a = tmp_path / "a.sf"
    b = tmp_path / "b.sf"
    write(a, [("G1", 1000, 100.0, 100.0), ("G2", 1000, 100.0, 100.0)])
    write(b, [("G1", 1000, 100.0, 0.0), ("G2", 1000, 100.0, 100.0)])

    merged = merge_quant._sum_runs([a, b])
    assert merged["G1"][3] == 100.0
    assert merged["G2"][3] == 200.0
    # equal lengths -> TPM proportional to summed counts (1:2)
    assert abs(merged["G1"][2] - 1e6 / 3) < 1
    assert abs(merged["G2"][2] - 2e6 / 3) < 1
