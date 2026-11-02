"""Tests for the SRA metadata parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_sra_metadata

SAMPLE_XML = b"""<?xml version="1.0" ?>
<EXPERIMENT_PACKAGE_SET>
  <EXPERIMENT_PACKAGE>
    <EXPERIMENT accession="SRX1">
      <TITLE>Arabidopsis RNA-seq</TITLE>
      <LIBRARY_DESCRIPTOR>
        <LIBRARY_NAME>lib1</LIBRARY_NAME>
        <LIBRARY_STRATEGY>RNA-Seq</LIBRARY_STRATEGY>
        <LIBRARY_SOURCE>TRANSCRIPTOMIC</LIBRARY_SOURCE>
        <LIBRARY_SELECTION>PolyA</LIBRARY_SELECTION>
        <LIBRARY_CONSTRUCTION_PROTOCOL>TruSeq polyA</LIBRARY_CONSTRUCTION_PROTOCOL>
      </LIBRARY_DESCRIPTOR>
      <EXPERIMENT_ATTRIBUTES>
        <EXPERIMENT_ATTRIBUTE>
          <TAG>library type</TAG>
          <VALUE>mRNA</VALUE>
        </EXPERIMENT_ATTRIBUTE>
      </EXPERIMENT_ATTRIBUTES>
    </EXPERIMENT>
    <SAMPLE accession="SRS1">
      <SUBMITTER_ID label="Sample name">sample1</SUBMITTER_ID>
      <SAMPLE_ATTRIBUTES>
        <SAMPLE_ATTRIBUTE>
          <TAG>tissue</TAG>
          <VALUE>leaf</VALUE>
        </SAMPLE_ATTRIBUTE>
      </SAMPLE_ATTRIBUTES>
    </SAMPLE>
    <STUDY accession="SRP1">
      <STUDY_TITLE>Study title</STUDY_TITLE>
      <STUDY_ABSTRACT>Abstract text.</STUDY_ABSTRACT>
    </STUDY>
    <RUN accession="SRR1"/>
  </EXPERIMENT_PACKAGE>
</EXPERIMENT_PACKAGE_SET>
"""


def test_parse_sra_library_fields():
    record = fetch_sra_metadata._parse(SAMPLE_XML)["SRR1"]
    assert record["library_name"] == "lib1"
    assert record["library_strategy"] == "RNA-Seq"
    assert record["library_source"] == "TRANSCRIPTOMIC"
    assert record["library_selection"] == "PolyA"
    assert record["library_construction_protocol"] == "TruSeq polyA"
    assert record["experiment_attributes"] == {"library type": "mRNA"}
    assert record["sample_attributes"] == {"tissue": "leaf"}
    assert record["sample_name"] == "sample1"
    assert record["study_title"] == "Study title"
