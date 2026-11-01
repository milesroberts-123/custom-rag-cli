"""Tests for the BioProject XML parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_bioproject

SAMPLE_XML = b"""<?xml version="1.0" ?>
<RecordSet>
  <DocumentSummary uid="1552792">
    <Project>
      <ProjectID>
        <ArchiveID accession="PRJNA1552792" archive="NCBI" id="1552792"/>
        <LocalID>bp0</LocalID>
      </ProjectID>
      <ProjectDescr>
        <Title>Loss of DNA Demethylase Enhances Arsenic Resistance</Title>
        <Description>DNA methylation dynamics regulate plant stress responses.</Description>
        <Grant GrantId="internal work">
          <Title>internal work</Title>
          <Agency abbr="internal work">internal work</Agency>
        </Grant>
        <Relevance>
          <Environmental>yes</Environmental>
        </Relevance>
      </ProjectDescr>
      <ProjectType>
        <ProjectTypeSubmission>
          <Target capture="eWhole" material="eGenome" sample_scope="eMultispecies"/>
          <Method method_type="eSequencing"/>
          <Objectives>
            <Data data_type="eRawSequenceReads"/>
          </Objectives>
          <IntendedDataTypeSet>
            <DataType>raw sequence reads</DataType>
          </IntendedDataTypeSet>
        </ProjectTypeSubmission>
      </ProjectType>
    </Project>
    <Submission last_update="2026-10-29" submission_id="SUB16555284" submitted="2026-10-29">
      <Description>
        <Organization role="owner" type="institute">
          <Name>Yale University</Name>
        </Organization>
        <Access>public</Access>
      </Description>
      <Action action_id="SUB16555284-bp0"/>
    </Submission>
  </DocumentSummary>
</RecordSet>
"""


def test_parse_bioproject():
    record = fetch_bioproject._parse(SAMPLE_XML, "PRJNA1552792")
    assert record["status"] == "ok"
    assert record["prjna"] == "PRJNA1552792"
    assert record["uid"] == "1552792"
    assert record["accession"] == "PRJNA1552792"
    assert record["title"].startswith("Loss of DNA Demethylase")
    assert record["organism"] is None
    assert record["project_type"]["data_types"] == ["raw sequence reads"]
    assert record["project_type"]["target"]["material"] == "eGenome"
    assert record["submission"]["organization"] == "Yale University"
    assert record["submission"]["access"] == "public"
    assert record["grant"]["grant_id"] == "internal work"


def test_parse_missing_project():
    record = fetch_bioproject._parse(b"<RecordSet/>", "PRJNA000000")
    assert record == {"prjna": "PRJNA000000", "status": "none"}
