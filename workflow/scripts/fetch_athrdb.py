"""Fetch curated Arabidopsis annotations from the PlantRNADB (ATHRDB) site.

The ATHRDB web API keys libraries by GEO GSM accession, so each run is first
mapped through its SRA experiment accession (SRX) to a GSM record in the NCBI
GEO DataSets database. All ATHRDB requests are issued serially from one
Snakemake job, with a configurable minimum interval between requests and an
optional request cap, so the site is never hammered at production scale.
Every failure mode writes a record instead of raising: ATHRDB is evidence,
never a blocking dependency.
"""

import csv
import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path

from ncbi import esearch_ids, esummary

ARABIDOPSIS = "arabidopsis thaliana"
GSM_SEARCH = re.compile(r"\bGSM\d+")
GSM_RE = re.compile(r"GSM\d+")


def is_arabidopsis(species):
    """Return True when a species string denotes Arabidopsis thaliana."""
    return (species or "").strip().lower().replace("_", " ") == ARABIDOPSIS


class RequestPacer:
    """Enforce a minimum interval between HTTP requests, with jitter.

    The gap between consecutive waits is at least ``min_interval`` seconds,
    plus a random amount up to ``jitter_fraction * min_interval`` when a
    random source is provided. Jitter is one-sided (never shortens the gap
    below the configured floor).
    """

    def __init__(
        self,
        min_interval_seconds,
        clock=time.monotonic,
        sleeper=time.sleep,
        rng=None,
        jitter_fraction=0.0,
    ):
        import random

        self.min_interval = max(0.0, float(min_interval_seconds))
        self.jitter_fraction = max(0.0, float(jitter_fraction))
        self.clock = clock
        self.sleeper = sleeper
        self.rng = rng or random.uniform
        self._last = None

    def wait(self):
        """Block until the configured interval has elapsed since the last call."""
        if self._last is None:
            self._last = self.clock()
            return
        remaining = self.min_interval - (self.clock() - self._last)
        if remaining < 0:
            remaining = 0.0
        delay = remaining
        if self.min_interval > 0 and self.jitter_fraction > 0:
            delay += self.rng(0.0, self.min_interval * self.jitter_fraction)
        if delay > 0:
            self.sleeper(delay)
        self._last = self.clock()


TABLE_RE = re.compile(r'<table class="info"[^>]*>(.*?)</table>', re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def _cell_texts(table_html):
    """Return the stripped text of every <td> cell in one table."""
    cells = []
    for raw in CELL_RE.findall(table_html):
        text = unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ")
        cells.append(" ".join(text.split()))
    return cells


def parse_athrdb_html(html_text):
    """Parse an ATHRDB library page into a flat annotation dict.

    Returns None when the page has no paired library tables, which is what the
    site returns for a GSM with no curated record.
    """
    tables = TABLE_RE.findall(html_text)
    if len(tables) < 2:
        return None
    first = _cell_texts(tables[0])
    second = _cell_texts(tables[1])
    if not first or not second:
        return None

    gsm = GSM_SEARCH.search(first[0])
    second_gsm = GSM_SEARCH.search(second[0])
    if not gsm or not second_gsm or gsm.group(0) != second_gsm.group(0):
        return None
    gsm = gsm.group(0)

    total_reads = None
    mapped_rate = None
    if len(first) >= 4:
        try:
            total_reads = int(first[2].replace(",", ""))
        except ValueError:
            total_reads = None
        try:
            mapped_rate = round(float(first[3].rstrip("%")) / 100.0, 4)
        except ValueError:
            mapped_rate = None

    if len(second) < 6:
        return None

    def clean(value):
        return value or None

    return {
        "gsm": gsm,
        "athrdb_title": clean(first[1]),
        "athrdb_tissue": clean(second[1]),
        "athrdb_genotype": clean(second[2]),
        "athrdb_ecotype": clean(second[3]),
        "athrdb_project": clean(second[4]),
        "athrdb_release_date": clean(second[5]),
        "athrdb_total_reads": total_reads,
        "athrdb_mapped_rate": mapped_rate,
    }


def gsm_from_summaries(result):
    """Pick the first GEO Sample accession from an ESummary result payload."""
    for uid in result.get("uids", []):
        record = result.get(uid) or {}
        if (record.get("entrytype") or "").upper() == "GSM":
            accession = record.get("accession") or ""
            if GSM_RE.fullmatch(accession):
                return accession
    return None


def find_gsm(srx, email, api_key, max_retries, timeout=120):
    """Map an SRA experiment accession to its GEO Sample accession."""
    ids = esearch_ids("gds", srx, email, api_key, max_retries, timeout=timeout)
    if not ids:
        return None
    result = esummary("gds", ids, email, api_key, max_retries, timeout=timeout)
    return gsm_from_summaries(result)


class AthrdbClient:
    """Query the ATHRDB Search endpoint with rate limiting and soft retries."""

    def __init__(
        self,
        base_url,
        min_interval_seconds,
        timeout,
        session=None,
        jitter_fraction=0.0,
    ):
        self.search_url = f"{base_url.rstrip('/')}"
        self.timeout = timeout
        self.session = session or _default_session()
        self.pacer = RequestPacer(min_interval_seconds, jitter_fraction=jitter_fraction)

    def fetch_library(self, gsm):
        """Return parsed annotations for one GSM, or None when not curated.

        Retries once on transient (5x) failures; other errors raise so the
        caller can record them without failing the rule.
        """
        url = f"{self.search_url}?query={gsm}/0/max/NAN/NAN/NAN/"
        last_error = None
        for _ in range(2):
            self.pacer.wait()
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code in (502, 503, 504):
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                return parse_athrdb_html(response.text)
            except Exception as error:  # noqa: BLE001
                last_error = error
        raise last_error if last_error else RuntimeError("ATHRDB request failed")


def _default_session():
    import requests

    return requests


def stub(run, gsm=None, queried=False, note=""):
    """Build a no-record or skipped record for one run."""
    return {
        "run": run,
        "gsm": gsm,
        "athrdb_hit": False,
        "athrdb_queried": queried,
        "athrdb_note": note,
        "athrdb_title": None,
        "athrdb_tissue": None,
        "athrdb_genotype": None,
        "athrdb_ecotype": None,
        "athrdb_project": None,
        "athrdb_release_date": None,
        "athrdb_total_reads": None,
        "athrdb_mapped_rate": None,
        "queried_at": None,
    }


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _classify(run, species, enabled, cap_reached):
    """Return a skip record when a run should not be queried, else None."""
    if not enabled:
        return stub(run, note="athrdb_disabled")
    if not is_arabidopsis(species):
        return stub(run, note="non_arabidopsis_species")
    if cap_reached:
        return stub(run, note="request_cap_reached")
    return None


def cap_stale(record, budget):
    """True when an existing file is a cap stub and request budget remains.

    Cap stubs are the only stubs worth retrying: everything else (disabled,
    non-Arabidopsis, no GEO record, request failures) is either permanent or
    would be re-attempted only by deleting the file.
    """
    return (
        isinstance(record, dict)
        and record.get("athrdb_note") == "request_cap_reached"
        and budget > 0
    )


from script_logging import setup as _setup

LOGGER = _setup("fetch_athrdb")


def main():
    runs = list(snakemake.params.runs)
    outputs = list(snakemake.output)
    if len(runs) != len(outputs):
        raise RuntimeError("run list and output list differ in length")
    sample_species = {}
    with open(snakemake.input.samples) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            sample_species[row["run"]] = row.get("species") or ""

    email = snakemake.params.email
    api_key = os.environ.get(snakemake.params.api_key_env or "")
    max_retries = int(snakemake.params.max_retries)
    athrdb = dict(snakemake.params.athrdb)
    enabled = bool(athrdb.get("enabled", True))
    max_requests = int(athrdb.get("max_requests") or 0)

    request_count = 0
    cached = stubbed = cap_stubbed = 0
    client = None
    sra_by_run = {Path(path).stem: path for path in snakemake.input.sra}
    for run, output_path in zip(runs, outputs):
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            with open(output) as handle:
                existing = json.load(handle)
            budget = 1 if not max_requests else max(0, max_requests - request_count)
            if not cap_stale(existing, budget):
                cached += 1
                continue
            # A cap stub with budget remaining falls through and is re-queried.

        skip = _classify(
            run,
            sample_species.get(run, ""),
            enabled,
            bool(max_requests) and request_count >= max_requests,
        )
        if skip is not None:
            record = skip
            LOGGER.info("%s: stub (%s)", run, record["athrdb_note"])
        else:
            with open(sra_by_run[run]) as handle:
                sra = json.load(handle)
            srx = (sra.get("experiment_accession") or "").strip()
            try:
                gsm = find_gsm(srx, email, api_key, max_retries) if srx else None
                if gsm is None:
                    record = stub(run, note="no_geo_record")
                    LOGGER.info(
                        "%s: stub (no_geo_record; srx=%s)", run, srx or "(none)"
                    )
                else:
                    if client is None:
                        client = AthrdbClient(
                            athrdb["base_url"],
                            athrdb.get("min_interval_seconds", 2.0),
                            athrdb.get("timeout", 60),
                            jitter_fraction=athrdb.get("jitter_fraction", 0.25),
                        )
                    request_count += 1
                    try:
                        parsed = client.fetch_library(gsm)
                    except Exception as error:  # noqa: BLE001
                        print(
                            f"ATHRDB query failed for {gsm}: {error}", file=sys.stderr
                        )
                        parsed = stub(run, gsm=gsm, queried=True, note="request_failed")
                    if isinstance(parsed, dict):
                        record = parsed
                        LOGGER.info("%s: %s (request %d)", run, gsm, request_count)
                    else:
                        record = stub(
                            run, gsm=gsm, queried=True, note="no_athrdb_record"
                        )
            except Exception as error:  # noqa: BLE001
                print(f"GEO lookup failed for {run}: {error}", file=sys.stderr)
                record = stub(run, note="geo_lookup_failed")

        record["run"] = run
        record["queried_at"] = _now()
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        note = record.get("athrdb_note")
        if note == "request_cap_reached":
            cap_stubbed += 1
        elif note:
            stubbed += 1

    LOGGER.info(
        "ATHRDB fetch done: %d queried, %d cached, %d stubbed, %d cap-stubbed",
        request_count,
        cached,
        stubbed,
        cap_stubbed,
    )


if __name__ == "__main__":
    main()
