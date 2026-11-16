"""Assign one of the configured tissue categories to a sample."""

import json
import re
import sys
from pathlib import Path

from chunk_runner import run_chunk

from evidence import (
    SAMPLE_PRECEDENCE,
    attribute_name,
    is_project_level,
    merge_sra,
    split_evidence,
)
from llm import chat_json, systemone
from skip import load_rna_type, write_skip

OTHER = "OTHER"

SYSTEM = (
    "You assign plant tissue categories to RNA-seq samples. Return only a JSON object."
)

PROMPT = """Per-sample evidence (this BioSample's own annotation):
{sample_evidence}

Project-level context (shared by every sample in the project):
{project_evidence}

{sample_precedence}

Allowed tissue categories:
{categories}

Choose exactly one category from the allowed list. Choose OTHER when no listed
category fits or the tissue is ambiguous.
Return JSON: {{"category": "<allowed category or OTHER>", "evidence": "short reason"}}
"""


def _structured_values(values, rule_keys):
    """Keep only lines whose attribute name is a structured tissue field.

    Free text (study titles, abstracts, paper conditions) stays available to
    the model but must not drive the rules layer: in the first window, 69% of
    rule labels came from such text rather than a tissue/organ-part field.
    `paper_tissue_sampled` normalizes to a name containing "tissue" and leaked
    through a substring match, which made 1,259 rule labels paper-derived.
    """
    keys = [key.lower().replace("_", " ") for key in rule_keys]
    selected = []
    for line in values:
        if is_project_level(line):
            continue
        name = attribute_name(line)
        if any(key in name for key in keys):
            selected.append(line)
    return selected


def _po_category(values, po_terms):
    """Resolve Plant Ontology IDs from structured ENA fields to a category."""
    text = " ".join(values).upper()
    hits = {
        category
        for po_id, category in (po_terms or {}).items()
        if re.search(rf"{re.escape(po_id.upper())}(?!\d)", text)
    }
    return hits.pop() if len(hits) == 1 else None


def _rules_category(values, categories, keywords, po_terms=None, rule_keys=None):
    """Return a category from structured evidence only.

    Plant Ontology IDs take precedence; keyword matching then runs on
    structured attribute lines. Multi-category evidence abstains.
    """
    structured = _structured_values(values, rule_keys or [])
    if not structured:
        return None

    category = _po_category(structured, po_terms)
    if category in categories:
        return category

    text = " | ".join(structured)
    hits = []
    for category in categories:
        for keyword in keywords.get(category, []):
            if re.search(rf"\b{re.escape(keyword)}\b", text, flags=re.IGNORECASE):
                hits.append(category)
                break
    return hits[0] if len(hits) == 1 else None


def _state(biosample, summary, values, sample, project):
    conditions = summary.get("conditions") if summary.get("has_paper") else None
    return {
        "attributes": values or ["(none)"],
        "sample_evidence": sample or ["(none)"],
        "project_context": project or ["(none)"],
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
                "Choose OTHER when no listed category fits. Weigh the sample's "
                "own annotation above project-level text shared by all samples."
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
    sample,
    project,
    categories,
    other_description,
):
    allowed = "\n".join(f"- {category}" for category in categories)
    allowed += f"\n- {OTHER}: {other_description}"
    prompt = PROMPT.format(
        sample_evidence="\n".join(sample) if sample else "(none)",
        project_evidence="\n".join(project) if project else "(none)",
        sample_precedence=SAMPLE_PRECEDENCE,
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


def _label_one(samn, runs, inputs, params):
    """Label a single run; returns the result dict."""
    rna_type = load_rna_type(inputs["rna_type"])
    if not rna_type.get("mrna_eligible"):
        write_skip(samn, runs, rna_type, inputs["output"])
        return None

    with open(inputs["biosample"]) as handle:
        biosample = json.load(handle)
    sras = []
    for path in inputs["sra"]:
        with open(path) as handle:
            sras.append(json.load(handle))
    sra = merge_sra(sras)
    with open(inputs["summary"]) as handle:
        summary = json.load(handle)

    categories = list(params["categories"])
    keywords = dict(params["keywords"])
    sample, project = split_evidence(
        biosample, sra, summary, list(params["attribute_keys"])
    )
    values = sample + project

    confidence = None
    probabilities = None
    category = _rules_category(
        values,
        categories,
        keywords,
        dict(params["po_terms"]),
        list(params["rule_attribute_keys"]),
    )
    if category is not None:
        source = "rules"
        evidence = "matched structured tissue evidence (Plant Ontology or keyword)"
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
                    _state(biosample, summary, values, sample, project),
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
                sample,
                project,
                categories,
                params["other_description"],
            )
            source = "chat_fallback" if fell_back else "chat"

    result = {
        "biosample": samn,
        "run": runs[0] if runs else None,
        "tissue": category,
        "source": source,
        "confidence": confidence,
        "probabilities": probabilities,
        "evidence": evidence,
        "attribute_values": values,
    }

    LOGGER.info(
        "%s: tissue=%s (source=%s, confidence=%s)",
        samn,
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
    items = list(zip(params["samns"], params["runs"], params["prjnas"]))

    def process(item):
        samn, runs, prjna = item
        _label_one(
            samn,
            runs,
            {
                "rna_type": f"results/rna_type/{samn}.json",
                "biosample": f"results/metadata/biosample/{samn}.json",
                "sra": [f"results/metadata/sra/{run}.json" for run in runs],
                "summary": f"results/summary/{prjna}.json",
                "output": f"results/tissue/{samn}.json",
            },
            params,
        )

    def stub(item, error):
        samn, runs, _ = item
        return {
            "biosample": samn,
            "run": runs[0] if runs else None,
            "layer": "tissue",
            "tissue": "OTHER",
            "source": "error",
            "confidence": None,
            "evidence": error,
        }

    run_chunk(
        items,
        lambda item: f"results/tissue/{item[0]}.json",
        process,
        stub,
        snakemake.output[0],
        LOGGER,
    )


if __name__ == "__main__":
    main()
