"""Tests for the quant shell-command builders.

These flags decide how much cluster time a run costs and how much disk it
leaves behind, so they are asserted rather than eyeballed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import quant_commands as qc


def test_fastp_never_deduplicates_rna_reads():
    command = qc.fastp_command(
        "SRR1",
        "SINGLE",
        ["raw.fq.gz"],
        "trim",
        "qc.json",
        "log.txt",
        4,
        False,
    )
    # Duplicate reads in RNA-seq are usually biological: --dedup must stay out.
    assert "--dedup" not in command


def test_fastp_single_uses_one_input_and_plain_trimmed_reads():
    command = qc.fastp_command(
        "SRR1", "SINGLE", ["raw.fq.gz"], "trim", "qc.json", "log.txt", 4, False
    )
    assert "-i raw.fq.gz" in command
    assert "-I" not in command
    assert "trim/SRR1.se.fq" in command
    assert "-w 4" in command


def test_fastp_paired_detects_adapters_and_compresses_when_asked():
    command = qc.fastp_command(
        "SRR2",
        "PAIRED",
        ["r1.fq.gz", "r2.fq.gz"],
        "trim",
        "qc.json",
        "log.txt",
        8,
        True,
    )
    assert "--detect_adapter_for_pe" in command
    assert "trim/SRR2_R1.fq.gz" in command
    assert "trim/SRR2_R2.fq.gz" in command


def test_trimmed_paths_match_what_fastp_writes():
    single = qc.trimmed_paths("SRR1", "SINGLE", "q/SAMN1/trim", False)
    paired = qc.trimmed_paths("SRR2", "PAIRED", "q/SAMN2/trim", True)
    assert [str(path) for path in single] == ["q/SAMN1/trim/SRR1.se.fq"]
    assert [str(path) for path in paired] == [
        "q/SAMN2/trim/SRR2_R1.fq.gz",
        "q/SAMN2/trim/SRR2_R2.fq.gz",
    ]


def test_salmon_pools_paired_runs_as_one_library():
    reads = ["a_R1.fq", "b_R1.fq", "a_R2.fq", "b_R2.fq"]
    command = qc.salmon_command(
        "out", reads, "PAIRED", "index", "tx2gene.tsv", 8, 250, 25
    )
    assert "-1 a_R1.fq b_R1.fq" in command
    assert "-2 a_R2.fq b_R2.fq" in command
    assert "-p 8" in command
    assert "--gcBias" in command and "--seqBias" in command


def test_salmon_single_sets_fragment_length_defaults():
    command = qc.salmon_command(
        "out", ["a.se.fq"], "SINGLE", "index", "tx2gene.tsv", 4, 250, 25
    )
    assert "-r a.se.fq" in command
    assert "--fldMean 250" in command and "--fldSD 25" in command
    assert "-1" not in command


def test_salmon_writes_mappings_for_tin():
    command = qc.salmon_command(
        "out", ["a.se.fq"], "SINGLE", "index", "tx2gene.tsv", 4, 250, 25
    )
    assert "--writeMappings=out/mappings.sam" in command


def test_to_bam_sorts_indexes_and_removes_the_sam():
    command = qc.to_bam_command("out")
    assert "samtools sort" in command
    assert "samtools index" in command
    assert "rm -f out/mappings.sam" in command
