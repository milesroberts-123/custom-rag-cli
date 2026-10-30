"""Assign one of the configured tissue categories to a sample."""

import json
import sys
from pathlib import Path

from llm import chat_json, make_client, systemone

OTHER = "OTHER"

SYSTEM = (
    "You assign plant tissue categories to RNA-seq samples. "
    "Return only a JSON object."
)

PROMPT = """Sample attributes from NCBI BioSample:
{attributes}

Paper conditions:
{paper}

Allowed tissue categories:
{categories}

Choose exactly one category from the allowed list. Choose OTHER when no listed
category fits or the tissue is ambiguous.
Return JSON: {{"category": "<allowed category or OTHER>", "evidence": "short reason"}}
"""


def _attribute_values(attributes, keys):
    values = []
    seen = set()
    for name, value in attributes.items():
        if any(key.lower() in name.lower() for key in keys):
            entry = f"{name}: {value}"
            if entry not in seen:
                values.append(entry)
                seen.add(entry)
    return values


def _rules_category(values, categories, keywords):
    text = " | ".join(values).lower()
    hits = [
        category
        for category in categories
        if any(keyword.lower() in text for keyword in keywords.get(category, []))
    ]
    return hits[0] if len(hits) == 1 else None


def _state(biosample, summary, values):
    conditions = summary.get("conditions") if summary.get("has_paper") else None
    return {
        "attributes": values or ["(none)"],
        "organism": biosample.get("organism"),
        "paper_conditions": conditions,
    }


def _decision(server_url, api_key, model, state, categories, other_description):
    criteria = {category: None for category in categories}
    criteria[OTHER] = other_description
    questions = {
        "tissue": {
            "type": "choice",
            "instructions": (
                "Which tissue category best describes this RNA-seq sample? "
                "Choose OTHER when no listed category fits."
            ),
            "criteria": criteria,
        }
    }
    response = systemone(server_url, api_key, model, state, questions)
    answer = (response.get("answers") or {}).get("tissue") or {}
    category = str(answer.get("choice", "")).strip()
    if category not in criteria:
        raise ValueError(f"decision model returned an invalid choice: {category!r}")
    return category, answer.get("confidence"), answer.get("probabilities")


def _chat(client, model, model_params, values, summary, categories, other_description):
    paper = (
        json.dumps(summary.get("conditions") or {}, sort_keys=True)
        if summary.get("has_paper")
        else "(no paper)"
    )
    allowed = "\n".join(f"- {category}" for category in categories)
    allowed += f"\n- {OTHER}: {other_description}"
    prompt = PROMPT.format(
        attributes="\n".join(values) if values else "(none)",
        paper=paper,
        categories=allowed,
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    for _ in range(3):
        try:
            parsed = chat_json(client, model, messages, model_params)
            category = str(parsed.get("category", "")).strip()
            if category in categories or category == OTHER:
                return category, str(parsed.get("evidence", "")).strip()
        except ValueError:
            continue
    return OTHER, ""


def main():
    with open(snakemake.input.biosample) as handle:
        biosample = json.load(handle)
    with open(snakemake.input.summary) as handle:
        summary = json.load(handle)

    categories = list(snakemake.params.categories)
    keywords = dict(snakemake.params.keywords)
    values = _attribute_values(
        biosample.get("attributes", {}), list(snakemake.params.attribute_keys)
    )

    confidence = None
    probabilities = None
    category = _rules_category(values, categories, keywords)
    if category is not None:
        source = "rules"
        evidence = "matched configured tissue keyword"
    elif not values:
        category = OTHER
        source = "missing_attributes"
        evidence = "no configured tissue attribute in the BioSample record"
    else:
        source = "chat"
        evidence = ""
        fell_back = False
        if snakemake.params.backend == "decision":
            try:
                category, confidence, probabilities = _decision(
                    snakemake.params.server_url,
                    snakemake.params.api_key,
                    snakemake.params.decision_model,
                    _state(biosample, summary, values),
                    categories,
                    snakemake.params.other_description,
                )
                source = "decision"
            except Exception as error:  # noqa: BLE001
                print(
                    f"decision model failed ({error}); falling back to chat",
                    file=sys.stderr,
                )
                fell_back = True

        if snakemake.params.backend == "chat" or fell_back:
            client = make_client(
                snakemake.params.server_url, snakemake.params.api_key
            )
            category, evidence = _chat(
                client,
                snakemake.params.model,
                snakemake.params.model_params,
                values,
                summary,
                categories,
                snakemake.params.other_description,
            )
            source = "chat_fallback" if fell_back else "chat"

    result = {
        "run": snakemake.wildcards.run,
        "tissue": category,
        "source": source,
        "confidence": confidence,
        "probabilities": probabilities,
        "evidence": evidence,
        "attribute_values": values,
    }

    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
