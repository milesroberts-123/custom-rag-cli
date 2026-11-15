"""Classify a sample as a natural Arabidopsis accession or a modified line."""

import json
import re
import sys
from pathlib import Path

from chunk_runner import run_chunk

from evidence import SAMPLE_PRECEDENCE, merge_sra, split_evidence
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
    # "genotype: wild type genotype" is a Col-0 record; without this token the
    # rules abstained and the model answered natural_accession at 0.99 for
    # 3,975 samples.
    "genotype",
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

PROMPT = """Per-sample evidence (this BioSample's own annotation):
{sample_evidence}

Project-level context (shared by every sample in the project):
{project_evidence}

{sample_precedence}

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


def _structured_values(values, rule_keys):
    """Keep only lines whose attribute name is a structured germplasm field.

    Study abstracts, sample names, and submitter IDs stay available to the
    model but must not drive the rules layer: an accession-shaped token in an
    ENA submitter ID once labeled a transgenic library as a natural accession.
    """
    keys = [key.lower().replace("_", " ") for key in rule_keys]
    selected = []
    for line in values:
        name = line.partition(":")[0].strip().lower().replace("_", " ")
        if name.startswith("sra "):
            name = name[4:]
        if any(key in name for key in keys):
            selected.append(line)
    return selected


def _matched_lines(structured, expressions):
    """Lines that match at least one expression (evidence for a category)."""
    return [
        line
        for line in structured
        if any(
            re.search(expression, line, flags=re.IGNORECASE)
            for expression in expressions
        )
    ]


HYBRID_KEYS = ("is hybrid", "ishybrid", "is_hybrid")


def _is_hybrid_line(line):
    """True when an evidence line comes from the ``is_hybrid`` attribute."""
    name = line.partition(":")[0].strip().lower().replace("_", " ")
    if name.startswith("sra "):
        name = name[4:]
    return name in HYBRID_KEYS


def _hybrid_values(values):
    """Values of the structured ``is_hybrid`` attribute, if present."""
    return [line.partition(":")[2].strip() for line in values if _is_hybrid_line(line)]


def _hybrid_vote(values, hybrid_values, inbred_values):
    """Read the structured ``is_hybrid`` attribute: 'hybrid', 'inbred' or None."""
    hybrid = {value.strip().lower() for value in hybrid_values or []}
    inbred = {value.strip().lower() for value in inbred_values or []}
    votes = set()
    for value in _hybrid_values(values):
        lowered = value.strip().lower()
        if lowered in hybrid:
            votes.add("hybrid")
        elif lowered in inbred:
            votes.add("inbred")
    return votes.pop() if len(votes) == 1 else None


def _hybrid_evidence(values, accepted):
    """Quote the is_hybrid line that carried the vote."""
    allowed = {value.strip().lower() for value in accepted}
    for value in _hybrid_values(values):
        if value.strip().lower() in allowed:
            return f"is_hybrid: {value.strip()}"
    return ""


def _hybrid_guard(category, values, inbred_values, accessions, patterns, rule_keys):
    """Veto a hybrid call when the record states the line is inbred.

    ENA's checklist carries ``is_hybrid`` (Hybrid/Inbred/NTC). A project titled
    "... A. thaliana hybrids" had 382 Inbred samples labelled hybrid by the
    model at confidence 0.63 — above the review threshold — so the structured
    attribute has to override the study title.
    """
    if category != "hybrid":
        return category, "", None
    inbred = {value.strip().lower() for value in inbred_values}
    seen = [value for value in _hybrid_values(values) if value.lower() in inbred]
    if not seen:
        return category, "", None

    # Re-run the rules without the is_hybrid line so a real mutant/transgenic
    # signal still wins; otherwise the line is an unmodified inbred accession.
    filtered = [line for line in values if not _is_hybrid_line(line)]
    alternative, alternative_evidence, _ = _rule_label(
        filtered, accessions, patterns, rule_keys
    )
    note = f"is_hybrid: {seen[0]}"
    if alternative and alternative != "hybrid":
        return (
            alternative,
            "; ".join(part for part in (alternative_evidence, note) if part),
            "rules_override",
        )
    return "natural_accession", note, "rules_override"


def _rule_label(
    values, accessions, patterns, rule_keys, hybrid_values=None, inbred_values=None
):
    vote = _hybrid_vote(values, hybrid_values, inbred_values)
    inbred_evidence = _hybrid_evidence(values, inbred_values or [])

    # A structured checklist value is near-certain evidence and decides before
    # the model is asked: the study title made the model call Inbred samples
    # hybrids in PRJEB51241.
    if vote == "hybrid":
        return "hybrid", _hybrid_evidence(values, hybrid_values or []), "rules"

    structured = _structured_values(values, rule_keys)
    if not structured:
        if vote == "inbred":
            return "natural_accession", inbred_evidence, "rules"
        return None, "", ""

    text = "\n".join(structured)
    hits = _pattern_hits(text, patterns)
    natural = _natural_hits(text, accessions)

    if hits:
        category = next((name for name in PRIORITY if name in hits), None)
        if category is None:
            category = sorted(hits)[0]
        if category == "hybrid" and vote == "inbred":
            # Genotype text says hybrid while the checklist says inbred: the
            # two structured signals disagree, so let the model arbitrate.
            return None, "", ""
        evidence = "; ".join(
            f"{name}: {', '.join(_matched_lines(structured, expressions)[:3])}"
            for name, expressions in hits.items()
        )
        return category, evidence, "rules"

    if natural and _natural_supported(values, accessions):
        return (
            "natural_accession",
            "matched natural accession: " + ", ".join(natural[:5]),
            "rules",
        )
    if vote == "inbred":
        return "natural_accession", inbred_evidence, "rules"
    return None, "", ""


def _state(values, summary, sample, project):
    conditions = summary.get("conditions") if summary.get("has_paper") else None
    return {
        "evidence": values,
        "sample_evidence": sample or ["(none)"],
        "project_context": project or ["(none)"],
        "paper_conditions": conditions,
    }


def _decision(server_url, api_key, model, state, categories, descriptions):
    criteria = {
        category: descriptions.get(category) or category for category in categories
    }
    questions = {
        "germplasm": {
            "type": "choice",
            "instructions": (
                "Which germplasm category best describes this RNA-seq sample? "
                "Use unknown when the evidence does not establish the genotype. "
                "Weigh the sample's own annotation above project-level text "
                "shared by all samples (a project titled 'hybrids' can still "
                "contain inbred lines)."
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


def _chat(
    server_url, api_key, model, model_params, sample, project, categories, descriptions
):
    allowed = "\n".join(
        f"- {category}: {descriptions.get(category, '')}" for category in categories
    )
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
            if category in categories:
                return category, str(parsed.get("evidence", "")).strip()
        except ValueError:
            continue
    return UNKNOWN, ""


from script_logging import setup as _setup

LOGGER = _setup("label_germplasm")


def _label_one(samn, runs, inputs, params):
    """Classify one run; returns the result dict or None when skipped."""
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
    descriptions = dict(params["descriptions"])
    sample, project = split_evidence(
        biosample, sra, summary, list(params["attribute_keys"])
    )
    values = sample + project

    category = None
    confidence = None
    probabilities = None
    evidence = ""
    source = ""

    if values:
        category, evidence, source = _rule_label(
            values,
            list(params["natural_accessions"]),
            dict(params["patterns"]),
            list(params["rule_attribute_keys"]),
            list(params.get("hybrid_values") or []),
            list(params.get("inbred_values") or []),
        )

        if category is None:
            fell_back = False
            if params["backend"] == "decision":
                try:
                    category, confidence, probabilities = _decision(
                        params["server_url"],
                        params["api_key"],
                        params["decision_model"],
                        _state(values, summary, sample, project),
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

            if params["backend"] == "chat" or fell_back:
                category, evidence = _chat(
                    params["server_url"],
                    params["api_key"],
                    params["model"],
                    params["model_params"],
                    sample,
                    project,
                    categories,
                    descriptions,
                )
                source = "chat_fallback" if fell_back else "chat"

    if category is not None:
        category, guard_evidence, guard_source = _hybrid_guard(
            category,
            values,
            list(params.get("inbred_values") or []),
            list(params["natural_accessions"]),
            dict(params["patterns"]),
            list(params["rule_attribute_keys"]),
        )
        if guard_source:
            evidence = guard_evidence
            source = guard_source
            confidence = None
            probabilities = None

    if category is None:
        category = UNKNOWN
        source = "missing_evidence"
        evidence = "no genotype, ecotype, experiment title, or paper summary"

    result = {
        "biosample": samn,
        "run": runs[0] if runs else None,
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
                "output": f"results/germplasm/{samn}.json",
            },
            params,
        )

    def stub(item, error):
        samn, runs, _ = item
        return {
            "biosample": samn,
            "run": runs[0] if runs else None,
            "layer": "germplasm",
            "germplasm_type": "unknown",
            "is_natural_accession": False,
            "source": "error",
            "confidence": None,
            "evidence": error,
        }

    run_chunk(
        items,
        lambda item: f"results/germplasm/{item[0]}.json",
        process,
        stub,
        snakemake.output[0],
        LOGGER,
    )


if __name__ == "__main__":
    main()
