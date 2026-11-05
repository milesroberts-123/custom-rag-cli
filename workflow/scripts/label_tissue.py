"""Assign one of the configured tissue categories to a sample."""

import json
import re
import sys
from pathlib import Path

from evidence import evidence_lines
from llm import chat_json, systemone
from skip import load_rna_type, write_skip

OTHER = "OTHER"

SYSTEM = (
    "You assign plant tissue categories to RNA-seq samples. Return only a JSON object."
)

PROMPT = """Sample evidence (BioSample, SRA metadata, paper):
{attributes}

Paper conditions:
{paper}

Allowed tissue categories:
{categories}

Choose exactly one category from the allowed list. Choose OTHER when no listed
category fits or the tissue is ambiguous.
Return JSON: {{"category": "<allowed category or OTHER>", "evidence": "short reason"}}
"""


def _rules_category(values, categories, keywords):
    text = " | ".join(values)
    hits = []
    for category in categories:
        for keyword in keywords.get(category, []):
            if re.search(rf"\b{re.escape(keyword)}\b", text, flags=re.IGNORECASE):
                hits.append(category)
                break
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


def _chat(
    server_url,
    api_key,
    model,
    model_params,
    values,
    summary,
    categories,
    other_description,
):
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
            parsed = chat_json(server_url, api_key, model, messages, model_params)
            category = str(parsed.get("category", "")).strip()
            if category in categories or category == OTHER:
                return category, str(parsed.get("evidence", "")).strip()
        except ValueError:
            continue
    return OTHER, ""


from script_logging import setup as _setup

LOGGER = _setup("label_tissue")


def _label_one(run, inputs, params):
    """Label a single run; returns the result dict."""
    rna_type = load_rna_type(inputs["rna_type"])
    if not rna_type.get("mrna_eligible"):
        write_skip(run, rna_type, inputs["output"])
        return None

    with open(inputs["biosample"]) as handle:
        biosample = json.load(handle)
    with open(inputs["sra"]) as handle:
        sra = json.load(handle)
    with open(inputs["summary"]) as handle:
        summary = json.load(handle)

    categories = list(params["categories"])
    keywords = dict(params["keywords"])
    values = evidence_lines(biosample, sra, summary, list(params["attribute_keys"]))

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
        if params["backend"] == "decision":
            try:
                category, confidence, probabilities = _decision(
                    params["server_url"],
                    params["api_key"],
                    params["decision_model"],
                    _state(biosample, summary, values),
                    categories,
                    params["other_description"],
                )
                source = "decision"
            except Exception as error:  # noqa: BLE001
                print(
                    f"decision model failed ({error}); falling back to chat",
                    file=sys.stderr,
                )
                fell_back = True

        if params["backend"] == "chat" or fell_back:
            category, evidence = _chat(
                params["server_url"],
                params["api_key"],
                params["model"],
                params["model_params"],
                values,
                summary,
                categories,
                params["other_description"],
            )
            source = "chat_fallback" if fell_back else "chat"

    result = {
        "run": run,
        "tissue": category,
        "source": source,
        "confidence": confidence,
        "probabilities": probabilities,
        "evidence": evidence,
        "attribute_values": values,
    }

    LOGGER.info(
        "%s: tissue=%s (source=%s, confidence=%s)",
        run,
        category,
        source,
        confidence,
    )
    output = Path(inputs["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    params = dict(snakemake.params)
    for run, samn, prjna in zip(params["runs"], params["samns"], params["prjnas"]):
        _label_one(
            run,
            {
                "rna_type": f"results/rna_type/{run}.json",
                "biosample": f"results/metadata/biosample/{samn}.json",
                "sra": f"results/metadata/sra/{run}.json",
                "summary": f"results/summary/{prjna}.json",
                "output": f"results/tissue/{run}.json",
            },
            params,
        )

    marker = Path(snakemake.output[0])
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"runs": len(params["runs"])}) + "\n")


if __name__ == "__main__":
    main()
