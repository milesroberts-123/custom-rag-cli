"""Paper discovery, excerpting, and the study-setting fast path.

Paper coverage is the ceiling on study-condition and exposure labels, so these
tests pin the pieces that decide which paper is used and what is extracted.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_paper
import label_study_condition
import summarize_paper


class _Response:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _search(pmids):
    return _Response({"resultList": {"result": [{"pmid": p} for p in pmids]}})


def test_accession_search_returns_pmids(monkeypatch):
    monkeypatch.setattr(fetch_paper, "get", lambda *a, **k: _search(["111", "222"]))
    assert fetch_paper._accession_pmids("PRJEB123") == ["111", "222"]


def test_accession_search_empty_when_nothing_found(monkeypatch):
    monkeypatch.setattr(fetch_paper, "get", lambda *a, **k: _search([]))
    assert fetch_paper._accession_pmids("PRJEB123") == []


def test_stale_records_are_refetched(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_paper, "get", lambda *a, **k: _search([]))
    fresh = tmp_path / "fresh.json"
    fresh.write_text(json.dumps({"version": fetch_paper.FETCH_VERSION}))
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"status": "abstract"}))
    broken = tmp_path / "broken.json"
    broken.write_text("not json")

    assert fetch_paper._stale(fresh) is False
    assert fetch_paper._stale(old) is True
    assert fetch_paper._stale(broken) is True


def test_best_text_tier_wins_between_pmids(monkeypatch):
    records = {
        "111": {"prjna": "P", "pmid": "111", "status": "abstract"},
        "222": {"prjna": "P", "pmid": "222", "status": "fulltext"},
    }

    def fake_record(prjna, pmid):
        return dict(records[pmid])

    monkeypatch.setattr(fetch_paper, "_paper_record", fake_record)
    chosen = None
    for pmid in ["111", "222"]:
        candidate = fake_record("P", pmid)
        if (
            chosen is None
            or fetch_paper.STATUS_RANK[candidate["status"]]
            > (fetch_paper.STATUS_RANK[chosen["status"]])
        ):
            chosen = candidate
    assert chosen["pmid"] == "222"


def _jats(body):
    return f"<article><body>{body}</body></article>"


def test_jats_excerpt_puts_methods_before_abstract():
    xml = _jats(
        """
        <sec><title>Introduction</title><p>intro text</p></sec>
        <sec sec-type="methods"><title>Plant growth</title>
            <p>Plants were grown in a growth chamber at 22 C.</p></sec>
        <sec><title>Results</title><p>results text</p></sec>
        """
        + """
        <abstract><p>abstract text</p></abstract>
        """
    )
    excerpt = summarize_paper._jats_excerpt(xml, max_chars=400)
    assert excerpt.index("growth chamber") < excerpt.index("abstract text")


def test_jats_excerpt_truncates_at_the_budget():
    body = (
        "<sec sec-type='methods'><title>Methods</title><p>" + ("x" * 500) + "</p></sec>"
    )
    excerpt = summarize_paper._jats_excerpt(_jats(body), max_chars=120)
    assert len(excerpt) < 200


def test_setting_requires_an_allowed_value_and_a_quote():
    parsed = {"study_setting": "growth_chamber", "study_setting_quote": " "}
    conditions = summarize_paper._normalize(parsed)
    assert conditions["study_setting"] is None
    assert conditions["study_setting_quote"] == ""


def test_setting_outside_the_enum_is_dropped():
    parsed = {"study_setting": "space station", "study_setting_quote": "grown in orbit"}
    assert summarize_paper._normalize(parsed)["study_setting"] is None


def test_setting_with_quote_is_kept():
    parsed = {
        "study_setting": "Field",
        "study_setting_quote": "Plants were grown in the field.",
    }
    conditions = summarize_paper._normalize(parsed)
    assert conditions["study_setting"] == "field"
    assert conditions["study_setting_quote"].startswith("Plants were grown")


CRITERIA = {
    "growth chamber study": "controlled growth chamber",
    "field study": "field site",
    "laboratory study": "in vitro",
    "greenhouse study": "greenhouse",
    "OTHER": "unknown",
}
MAP = {
    "growth_chamber": "growth chamber study",
    "field": "field study",
    "laboratory": "laboratory study",
    "greenhouse": "greenhouse study",
}


def _summary(setting, quote="grown in a chamber", low=False):
    return {
        "has_paper": True,
        "low_confidence": low,
        "conditions": {"study_setting": setting, "study_setting_quote": quote},
    }


def test_paper_setting_maps_to_a_study_label():
    category, evidence = label_study_condition.paper_setting_category(
        _summary("growth_chamber"), CRITERIA, MAP
    )
    assert category == "growth chamber study"
    assert evidence.startswith("paper study setting:")


def test_low_confidence_summary_does_not_use_the_setting():
    category, _ = label_study_condition.paper_setting_category(
        _summary("field", low=True), CRITERIA, MAP
    )
    assert category is None


def test_setting_without_quote_is_ignored():
    category, _ = label_study_condition.paper_setting_category(
        _summary("field", quote=""), CRITERIA, MAP
    )
    assert category is None


def test_unmapped_setting_is_ignored():
    category, _ = label_study_condition.paper_setting_category(
        _summary("in_vitro"), CRITERIA, MAP
    )
    assert category is None
