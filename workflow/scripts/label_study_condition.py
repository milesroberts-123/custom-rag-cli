"""Assign a PECO plant study condition to a sample."""

import json
import sys
from pathlib import Path

from evidence import evidence_lines
from llm import chat_json, make_client, systemone
from skip import load_rna_type, write_skip

OTHER = "OTHER"

SYSTEM = (
    "You classify the study setting of Arabidopsis RNA-seq samples using the "
    "Plant Experimental Conditions Ontology (PECO). Return only a JSON object."
)

PROMPT = """Sample and paper evidence:
{evidence}

Allowed study conditions:
{conditions}

Choose exactly one study condition. Use OTHER when the evidence does not
establish where the plants were grown.
Return JSON: {{"category": "<allowed condition or OTHER>", "evidence": "short reason"}}
"""


def _load_terms(index_dir):
    terms = json.loads((Path(index_dir) / "terms.json").read_text())
    study_terms = [term for term in terms if term.get("branch") == "study_condition"]
    if not study_terms:
        raise RuntimeError("the PECO index has no plant study condition terms")
    return study_terms


def _criteria(study_terms):
    criteria = {
        term["label"]: term["definition"] or term["label"] for term in study_terms
    }
    criteria[OTHER] = "The evidence does not establish the study setting."
    return criteria


def _decision(server_url, api_key, model, state, criteria):
    questions = {
        "study_condition": {
            "type": "choice",
            "instructions": (
                "Where were the plants grown? Choose the PECO plant study "
                "condition that best matches the evidence, or OTHER."
            ),
            "criteria": criteria,
        }
    }
    response = systemone(server_url, api_key, model, state, questions)
    answer = (response.get("answers") or {}).get("study_condition") or {}
    category = str(answer.get("choice", "")).strip()
    if category not in criteria:
        raise ValueError(f"decision model returned an invalid choice: {category!r}")
    return category, answer.get("confidence"), answer.get("probabilities")


def _chat(client, model, model_params, values, criteria):
    allowed = "\n".join(f"- {label}: {text}" for label, text in criteria.items())
    prompt = PROMPT.format(
        evidence="\n".join(values) if values else "(none)",
        conditions=allowed,
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    for _ in range(3):
        try:
            parsed = chat_json(client, model, messages, model_params)
            category = str(parsed.get("category", "")).strip()
            if category in criteria:
                return category, str(parsed.get("evidence", "")).strip()
        except ValueError:
            continue
    return OTHER, ""


from script_logging import setup as _setup

LOGGER = _setup("label_study_condition")


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

    study_terms = _load_terms(snakemake.input.index)
    criteria = _criteria(study_terms)
    term_by_label = {term["label"]: term for term in study_terms}
    values = evidence_lines(biosample, sra, summary)

    category = None
    confidence = None
    probabilities = None
    evidence = ""
    source = ""

    if values:
        fell_back = False
        if snakemake.params.backend == "decision":
            try:
                category, confidence, probabilities = _decision(
                    snakemake.params.server_url,
                    snakemake.params.api_key,
                    snakemake.params.decision_model,
                    {"evidence": values},
                    criteria,
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
            client = make_client(snakemake.params.server_url, snakemake.params.api_key)
            category, evidence = _chat(
                client,
                snakemake.params.model,
                snakemake.params.model_params,
                values,
                criteria,
            )
            source = "chat_fallback" if fell_back else "chat"

    if category is None:
        category = OTHER
        source = "missing_evidence"
        evidence = "no growth setting, study title, or paper summary"

    term = term_by_label.get(category)
    result = {
        "run": snakemake.wildcards.run,
        "layer": "study_condition",
        "term_id": term["id"] if term else None,
        "label": term["label"] if term else OTHER,
        "other": term is None,
        "confidence": confidence,
        "probabilities": probabilities,
        "evidence": evidence,
        "source": source,
        "attribute_values": values,
    }

    LOGGER.info(
        "%s: study_condition=%s (source=%s, confidence=%s)",
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
