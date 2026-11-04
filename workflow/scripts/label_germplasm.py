"""Classify a sample as a natural Arabidopsis accession or a modified line."""

import json
import re
import sys
from pathlib import Path

from evidence import evidence_lines
from llm import chat_json, systemone
from skip import load_rna_type, write_skip

UNKNOWN = "unknown"

PRIORITY = (
    "cell_culture",
    "grafted",
    "hybrid",
    "polyploid",
    "aneuploid",
    "transgenic",
    "mutant",
)

GENOTYPE_KEYS = ("genotype", "ecotype", "cultivar", "strain")
NEUTRAL_GENOTYPE_TOKENS = {
    "wild",
    "type",
    "wildtype",
    "wt",
    "na",
    "n/a",
    "none",
    "unknown",
    "not",
    "applicable",
}
ACCESSION_RE = re.compile(r"[A-Z][a-zA-Z]{1,5}-\d+")

SYSTEM = (
    "You classify Arabidopsis thaliana RNA-seq samples by germplasm type. "
    "Return only a JSON object."
)

PROMPT = """Sample evidence:
{evidence}

Allowed germplasm categories:
{categories}

Choose exactly one category. Use unknown when the evidence is insufficient.
Return JSON: {{"category": "<allowed category>", "evidence": "short reason"}}
"""


def _pattern_hits(text, patterns):
    hits = {}
    for category, expressions in patterns.items():
        matched = [
            expression
            for expression in expressions
            if re.search(expression, text, flags=re.IGNORECASE)
        ]
        if matched:
            hits[category] = matched
    return hits


def _natural_hits(text, accessions):
    hits = []
    for accession in accessions:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(accession)}(?![A-Za-z0-9])"
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(accession)
    for match in re.finditer(r"\b[A-Z][a-zA-Z]{1,5}-\d+\b", text):
        hits.append(match.group(0))
    return sorted(set(hits), key=str.lower)


def _natural_supported(values, accessions):
    """Reject a natural-accession rule when the genotype field has other tokens."""
    allowed = {accession.lower() for accession in accessions}
    allowed |= NEUTRAL_GENOTYPE_TOKENS
    genotype_values = []
    for line in values:
        name, _, value = line.partition(":")
        if any(key in name.lower() for key in GENOTYPE_KEYS):
            genotype_values.append(value.strip())
    if not genotype_values:
        return True

    for value in genotype_values:
        for token in re.findall(r"[A-Za-z0-9_./-]+", value):
            lowered = token.lower()
            if lowered in allowed or ACCESSION_RE.fullmatch(token):
                continue
            return False
    return True


def _rule_label(values, accessions, patterns):
    text = "\n".join(values)
    hits = _pattern_hits(text, patterns)
    natural = _natural_hits(text, accessions)

    if hits:
        category = next((name for name in PRIORITY if name in hits), None)
        if category is None:
            category = sorted(hits)[0]
        evidence = "; ".join(
            f"{name}: {', '.join(values[:3])}" for name, values in sorted(hits.items())
        )
        return category, evidence, "rules"

    if natural and _natural_supported(values, accessions):
        return (
            "natural_accession",
            "matched natural accession: " + ", ".join(natural[:5]),
            "rules",
        )
    return None, "", ""


def _state(values, summary):
    conditions = summary.get("conditions") if summary.get("has_paper") else None
    return {"evidence": values, "paper_conditions": conditions}


def _decision(server_url, api_key, model, state, categories, descriptions):
    criteria = {
        category: descriptions.get(category) or category for category in categories
    }
    questions = {
        "germplasm": {
            "type": "choice",
            "instructions": (
                "Which germplasm category best describes this RNA-seq sample? "
                "Use unknown when the evidence does not establish the genotype."
            ),
            "criteria": criteria,
        }
    }
    response = systemone(server_url, api_key, model, state, questions)
    answer = (response.get("answers") or {}).get("germplasm") or {}
    category = str(answer.get("choice", "")).strip()
    if category not in criteria:
        raise ValueError(f"decision model returned an invalid choice: {category!r}")
    return category, answer.get("confidence"), answer.get("probabilities")


def _chat(server_url, api_key, model, model_params, values, categories, descriptions):
    allowed = "\n".join(
        f"- {category}: {descriptions.get(category, '')}" for category in categories
    )
    prompt = PROMPT.format(
        evidence="\n".join(values) if values else "(none)",
        categories=allowed,
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    for _ in range(3):
        try:
            parsed = chat_json(server_url, api_key, model, messages, model_params)
            category = str(parsed.get("category", "")).strip()
            if category in categories:
                return category, str(parsed.get("evidence", "")).strip()
        except ValueError:
            continue
    return UNKNOWN, ""


def athrdb_lines(record):
    """Return curated genotype/ecotype evidence lines from an ATHRDB record."""
    lines = []
    if not record or not record.get("athrdb_hit"):
        return lines
    genotype = record.get("athrdb_genotype")
    if genotype:
        lines.append(f"athrdb_genotype: {genotype}")
    ecotype = record.get("athrdb_ecotype")
    if ecotype and ecotype != genotype:
        lines.append(f"athrdb_ecotype: {ecotype}")
    return lines


from script_logging import setup as _setup

LOGGER = _setup("label_germplasm")


def main():
    rna_type = load_rna_type(snakemake.input.rna_type)
    if not rna_type.get("mrna_eligible"):
        write_skip(snakemake.wildcards.run, rna_type, snakemake.output[0])
        return

    with open(snakemake.input.biosample) as handle:
        biosample = json.load(handle)
    with open(snakemake.input.sra) as handle:
        sra = json.load(handle)
    with open(snakemake.input.summary) as handle:
        summary = json.load(handle)
    with open(snakemake.input.athrdb) as handle:
        athrdb = json.load(handle)

    categories = list(snakemake.params.categories)
    descriptions = dict(snakemake.params.descriptions)
    values = evidence_lines(
        biosample, sra, summary, list(snakemake.params.attribute_keys)
    )
    values.extend(athrdb_lines(athrdb))

    category = None
    confidence = None
    probabilities = None
    evidence = ""
    source = ""

    if values:
        category, evidence, source = _rule_label(
            values,
            list(snakemake.params.natural_accessions),
            dict(snakemake.params.patterns),
        )

        if category is None:
            fell_back = False
            if snakemake.params.backend == "decision":
                try:
                    category, confidence, probabilities = _decision(
                        snakemake.params.server_url,
                        snakemake.params.api_key,
                        snakemake.params.decision_model,
                        _state(values, summary),
                        categories,
                        descriptions,
                    )
                    source = "decision"
                    evidence = "; ".join(values[:3])
                except Exception as error:  # noqa: BLE001
                    print(
                        f"decision model failed ({error}); falling back to chat",
                        file=sys.stderr,
                    )
                    fell_back = True

            if snakemake.params.backend == "chat" or fell_back:
                category, evidence = _chat(
                    snakemake.params.server_url,
                    snakemake.params.api_key,
                    snakemake.params.model,
                    snakemake.params.model_params,
                    values,
                    categories,
                    descriptions,
                )
                source = "chat_fallback" if fell_back else "chat"

    if category is None:
        category = UNKNOWN
        source = "missing_evidence"
        evidence = "no genotype, ecotype, experiment title, or paper summary"

    result = {
        "run": snakemake.wildcards.run,
        "germplasm_type": category,
        "is_natural_accession": category == "natural_accession",
        "confidence": confidence,
        "probabilities": probabilities,
        "evidence": evidence,
        "source": source,
        "attribute_values": values,
    }

    LOGGER.info(
        "%s: germplasm=%s (source=%s, confidence=%s)",
        snakemake.wildcards.run,
        category,
        source,
        confidence,
    )
    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
