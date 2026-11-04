"""Classify the RNA species sequenced for one SRA run."""

import json
import re
import sys
from pathlib import Path

from llm import chat_json, systemone

MRNA = "mrna"
RIBO = "ribo_depleted_total_rna"
TOTAL = "total_rna"
SMALL = "small_rna"
LNCRNA = "lncrna"
CIRCRNA = "circrna"
OTHER = "other_rna"
NOT_RNA = "not_rna"
UNKNOWN = "unknown"

CATEGORIES = (
    MRNA,
    RIBO,
    TOTAL,
    SMALL,
    LNCRNA,
    CIRCRNA,
    OTHER,
    NOT_RNA,
    UNKNOWN,
)

DESCRIPTIONS = {
    MRNA: "PolyA-selected or oligo(dT)-primed mRNA sequencing.",
    RIBO: "Total RNA with ribosomal RNA depleted (for example RiboZero).",
    TOTAL: "Total RNA without ribosomal RNA depletion.",
    SMALL: "Small RNA sequencing, including miRNA, piRNA, siRNA, or snoRNA.",
    LNCRNA: "Long non-coding RNA sequencing.",
    CIRCRNA: "Circular RNA sequencing.",
    OTHER: "Another RNA assay that is not mRNA, total RNA, or small RNA.",
    NOT_RNA: "A DNA assay such as WGS, ChIP-Seq, ATAC-seq, or Bisulfite-Seq.",
    UNKNOWN: "The metadata does not establish which RNA species was sequenced.",
}

SMALL_SUBTYPES = (
    ("mirna", (r"\bmirna\b", r"\bmicro[- ]?rna\b")),
    ("pirna", (r"\bpirna\b", r"\bpiwi[- ]interacting rna\b")),
    ("sirna", (r"\bsirna\b", r"\bsmall interfering rna\b")),
    ("snorna", (r"\bsnorna\b", r"\bsmall nucleolar rna\b")),
    ("snrna", (r"\bsnrna\b", r"\bsmall nuclear rna\b")),
    ("trna", (r"\btrna\b", r"\btransfer rna\b")),
    ("other", (r"\bsmall rna\b", r"\bsrna\b")),
)

TEXT_PATTERNS = {
    MRNA: (
        r"\bmrna\b",
        r"\bmessenger rna\b",
        r"\bpoly[- ]?\(?a\)?",
        r"\boligo[- ]?\(?dt\)?",
        r"\bpolyadenyl\w*\b",
    ),
    RIBO: (
        r"\bribo[- ]?zero\b",
        r"\brrna[- ]?deplet\w*\b",
        r"\bribosomal rna[- ]?deplet\w*\b",
        r"\bribo[- ]?deplet\w*\b",
        r"\brna[- ]?deplet\w*\b",
        r"\brrna[- ]?remov\w*\b",
    ),
    TOTAL: (r"\btotal rna\b", r"\bwhole rna\b"),
    LNCRNA: (r"\blncrna\b", r"\blong non[- ]?coding rna\b"),
    CIRCRNA: (r"\bcircrna\b", r"\bcircular rna\b"),
    NOT_RNA: (
        r"\bwgs\b",
        r"\bwhole genome sequencing\b",
        r"\bexome\b",
        r"\bchip[- ]seq\b",
        r"\batac[- ]seq\b",
        r"\bbisulfite[- ]seq\b",
        r"\bhi[- ]c\b",
        r"\bdnase[- ]seq\b",
        r"\brad[- ]seq\b",
    ),
}

NOT_RNA_STRATEGIES = {
    "wgs",
    "wes",
    "chip-seq",
    "atac-seq",
    "dnase-hypersensitivity",
    "bisulfite-seq",
    "hi-c",
    "rad-seq",
    "gbs",
}

SMALL_STRATEGIES = {"mirna-seq": "mirna"}

SYSTEM = (
    "You classify RNA-seq library metadata by the RNA species that was "
    "sequenced. Return only a JSON object."
)

PROMPT = """Library and sample evidence:
{evidence}

Allowed RNA types:
{categories}

Choose exactly one RNA type. Use unknown when the evidence does not establish
which RNA species was sequenced.
Return JSON: {{"rna_type": "<allowed type>", "rna_subtype": null, "confidence": 0.0, "evidence": "short reason"}}
"""


def _matches(patterns, text):
    return [
        pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)
    ]


def _small_subtype(text):
    for subtype, patterns in SMALL_SUBTYPES:
        if _matches(patterns, text):
            return subtype
    return None


def _attribute_items(attributes, keys):
    for name, value in sorted((attributes or {}).items()):
        if keys and not any(key.lower() in name.lower() for key in keys):
            continue
        if value:
            yield name, value


def _evidence_lines(biosample, sra, attribute_keys):
    lines = []
    for key in (
        "library_strategy",
        "library_selection",
        "library_source",
        "library_construction_protocol",
        "experiment_title",
        "library_name",
        "sample_name",
    ):
        value = sra.get(key)
        if value:
            lines.append(f"{key}: {value}")

    for name, value in _attribute_items(
        sra.get("experiment_attributes"), attribute_keys
    ):
        lines.append(f"experiment_attribute_{name}: {value}")
    for name, value in _attribute_items(sra.get("sample_attributes"), attribute_keys):
        lines.append(f"sra_sample_attribute_{name}: {value}")
    for name, value in _attribute_items(biosample.get("attributes"), attribute_keys):
        lines.append(f"biosample_attribute_{name}: {value}")

    seen = set()
    unique = []
    for line in lines:
        key = line.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(line)
    return unique


def _add(candidates, category, evidence):
    candidates.setdefault(category, []).append(evidence)


def _strategy_candidates(strategy, candidates):
    value = (strategy or "").strip().lower()
    if not value:
        return
    if value in SMALL_STRATEGIES:
        _add(candidates, SMALL, f"library_strategy: {strategy}")
        _add(candidates, f"{SMALL}:{SMALL_STRATEGIES[value]}", "")
        return
    if value in NOT_RNA_STRATEGIES:
        _add(candidates, NOT_RNA, f"library_strategy: {strategy}")
        return
    if value == "ncrna-seq":
        _add(candidates, OTHER, f"library_strategy: {strategy}")
    if value == "rna-seq":
        return


def _selection_candidates(selection, candidates):
    value = (selection or "").strip().lower()
    if not value:
        return
    if re.search(r"\bpoly[- ]?\(?a\)?|\boligo[- ]?\(?dt\)?", value):
        _add(candidates, MRNA, f"library_selection: {selection}")
    if re.search(r"\bribo[- ]?zero\b|\brrna[- ]?deplet|\bribo[- ]?deplet", value):
        _add(candidates, RIBO, f"library_selection: {selection}")
    if "size fraction" in value:
        _add(candidates, SMALL, f"library_selection: {selection}")


def _text_candidates(lines, candidates):
    text = "\n".join(lines)
    for category, patterns in TEXT_PATTERNS.items():
        matched = _matches(patterns, text)
        if matched:
            _add(candidates, category, f"text: {matched[0]}")
    subtype = _small_subtype(text)
    if subtype:
        _add(candidates, SMALL, f"small RNA subtype: {subtype}")
        _add(candidates, f"{SMALL}:{subtype}", "")


def _resolve(candidates):
    rna_categories = set(candidates) - {
        f"{SMALL}:{subtype}" for subtype, _ in SMALL_SUBTYPES
    }

    # "Total RNA" often describes the input even when a polyA, ribo-depleted,
    # or small-RNA library was prepared. Treat it as a fallback only.
    if len(rna_categories) > 1 and TOTAL in rna_categories:
        candidates.pop(TOTAL, None)
        rna_categories.discard(TOTAL)
    if SMALL in rna_categories and OTHER in rna_categories:
        candidates.pop(OTHER, None)
        rna_categories.discard(OTHER)
    if LNCRNA in rna_categories and OTHER in rna_categories:
        candidates.pop(OTHER, None)
        rna_categories.discard(OTHER)
    if CIRCRNA in rna_categories and OTHER in rna_categories:
        candidates.pop(OTHER, None)
        rna_categories.discard(OTHER)

    if len(rna_categories) > 1:
        evidence = "; ".join(
            item for values in candidates.values() for item in values if item
        )
        return UNKNOWN, None, evidence
    if not rna_categories:
        return None

    category = next(iter(rna_categories))
    subtype = None
    if category == SMALL:
        for subtype_name, _ in SMALL_SUBTYPES:
            if f"{SMALL}:{subtype_name}" in candidates:
                subtype = subtype_name
                break
    evidence = "; ".join(item for item in candidates[category] if item)
    return category, subtype, evidence


def _classify_rules(biosample, sra, attribute_keys):
    candidates = {}
    _strategy_candidates(sra.get("library_strategy"), candidates)
    _selection_candidates(sra.get("library_selection"), candidates)
    lines = _evidence_lines(biosample, sra, attribute_keys)
    _text_candidates(lines, candidates)
    return _resolve(candidates)


def _state(lines, sra):
    return {
        "evidence": lines or ["(none)"],
        "library_strategy": sra.get("library_strategy"),
        "library_selection": sra.get("library_selection"),
    }


def _decision(server_url, api_key, model, state):
    criteria = {category: DESCRIPTIONS[category] for category in CATEGORIES}
    questions = {
        "rna_type": {
            "type": "choice",
            "instructions": (
                "Which RNA species was sequenced in this library? "
                "Use unknown when the evidence is insufficient."
            ),
            "criteria": criteria,
        }
    }
    response = systemone(server_url, api_key, model, state, questions)
    answer = (response.get("answers") or {}).get("rna_type") or {}
    category = str(answer.get("choice", "")).strip()
    if category not in criteria:
        raise ValueError(f"decision model returned an invalid choice: {category!r}")
    return category, answer.get("confidence"), answer.get("probabilities")


def _chat(server_url, api_key, model, model_params, lines):
    allowed = "\n".join(
        f"- {category}: {DESCRIPTIONS[category]}" for category in CATEGORIES
    )
    prompt = PROMPT.format(
        evidence="\n".join(lines) if lines else "(none)",
        categories=allowed,
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    for _ in range(3):
        try:
            parsed = chat_json(server_url, api_key, model, messages, model_params)
            category = str(parsed.get("rna_type", "")).strip()
            if category in CATEGORIES:
                confidence = parsed.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.0
                subtype = parsed.get("rna_subtype")
                if category != SMALL:
                    subtype = None
                return category, subtype, confidence, str(parsed.get("evidence", ""))
        except ValueError:
            continue
    return UNKNOWN, None, 0.0, ""


from script_logging import setup as _setup

LOGGER = _setup("classify_rna_type")


def main():
    with open(snakemake.input.biosample) as handle:
        biosample = json.load(handle)
    with open(snakemake.input.sra) as handle:
        sra = json.load(handle)

    attribute_keys = list(snakemake.params.attribute_keys)
    lines = _evidence_lines(biosample, sra, attribute_keys)
    classification = _classify_rules(biosample, sra, attribute_keys)
    if classification is None:
        category, subtype, evidence = None, None, ""
    else:
        category, subtype, evidence = classification
    confidence = None
    probabilities = None
    source = "rules" if category else ""

    if category == UNKNOWN:
        source = "rules_conflict"
    elif category is None:
        if snakemake.params.backend != "rules" and lines:
            fell_back = False
            if snakemake.params.backend == "decision":
                try:
                    category, confidence, probabilities = _decision(
                        snakemake.params.server_url,
                        snakemake.params.api_key,
                        snakemake.params.decision_model,
                        _state(lines, sra),
                    )
                    source = "decision"
                    evidence = "; ".join(lines[:3])
                except Exception as error:  # noqa: BLE001
                    print(
                        f"decision model failed ({error}); falling back to chat",
                        file=sys.stderr,
                    )
                    fell_back = True

            if snakemake.params.backend == "chat" or fell_back:
                category, subtype, chat_confidence, evidence = _chat(
                    snakemake.params.server_url,
                    snakemake.params.api_key,
                    snakemake.params.model,
                    snakemake.params.model_params,
                    lines,
                )
                confidence = chat_confidence
                source = "chat_fallback" if fell_back else "chat"

        if category is None:
            category = UNKNOWN
            source = "missing_metadata"
            evidence = "no RNA type in BioSample or SRA library metadata"

    if category not in CATEGORIES:
        category = UNKNOWN
        subtype = None
        source = "invalid_model_output"
        evidence = "model returned an unsupported RNA type"

    if (
        source in {"decision", "chat", "chat_fallback"}
        and category != UNKNOWN
        and (
            confidence is None
            or float(confidence) < float(snakemake.params.min_confidence)
        )
    ):
        category = UNKNOWN
        subtype = None
        source = "low_confidence"
        evidence = f"model confidence below {snakemake.params.min_confidence}"

    eligible_types = set(snakemake.params.accepted_rna_types)
    result = {
        "run": snakemake.wildcards.run,
        "rna_type": category,
        "rna_subtype": subtype,
        "ribo_depleted": category == RIBO,
        "mrna_eligible": category in eligible_types,
        "confidence": confidence,
        "probabilities": probabilities,
        "source": source,
        "evidence": evidence,
        "attribute_values": lines,
    }

    LOGGER.info(
        "%s: rna_type=%s%s (source=%s, confidence=%s)",
        snakemake.wildcards.run,
        category,
        f":{subtype}" if subtype else "",
        source,
        confidence,
    )
    output = Path(snakemake.output[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
