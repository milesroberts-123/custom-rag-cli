"""Assign plant exposure PECO terms to a sample using retrieval and an LLM."""

import json
import re
from pathlib import Path

import numpy as np
from chunk_runner import run_chunk
from sentence_transformers import SentenceTransformer

from evidence import evidence_lines, exposure_evidence, merge_sra
from llm import chat_json
from peco_utils import ancestor_map, prune_ancestors
from skip import load_rna_type, write_skip

SYSTEM = (
    "You are a plant biology curator mapping RNA-seq sample conditions to the "
    "Plant Experimental Conditions Ontology (PECO). Return only a JSON object."
)

PROMPT = """Per-sample evidence (this run only):
{sample_evidence}

Project-level context (shared by all runs in the project):
{project_evidence}

Candidate PECO plant exposure terms (ID | label | definition):
{candidates}

Select the PECO plant exposure term(s) that describe the experimental
conditions of this sample. Use only term IDs from the candidate list.

Annotation guidance:
- Every selected term must be supported by per-sample evidence. Project-level
  context (study abstract, paper conditions) may only confirm or disambiguate
  a term that per-sample evidence already suggests; it is never the sole basis
  for a term. If a condition appears only in project-level text and the
  per-sample evidence is silent, do not select it.
- Cite the supporting per-sample evidence in each term's "evidence" field, in
  at most 120 characters. Do not paste long attribute values or library names.
- Select at most 5 terms.
- Do not co-select "temperature exposure" with a biotic exposure term (insect,
  fungal, bacterial, metazoan, pathogen, or similar) unless the per-sample
  evidence names the organism.
- For an untreated control sample, prefer the "control exposure" term over
  "no_condition". Use "no_condition" only when there is no exposure to
  annotate at all.
- Exposure means an external treatment or environmental condition (pathogen,
  chemical, light, temperature, water, or nutrient treatment). Genotype,
  developmental stage, sampling time point, and study setting are NOT
  exposures and must not be labeled.
- Prefer the most specific candidate term. Do not select a parent term when a
  more specific candidate covers the same condition.
- control exposure: long-day (>= 12 h light, not constant), 18-26 C, with no
  explicit stress or nutrient limitation.
- high temperature: >= 27 C; cold: <= 17 C; short day: < 12 h light.
- Samples recovering from stress are labeled by the recovery condition.
- Multiple exposure terms are allowed when several stresses apply.
- If the sample has no experimental exposure to annotate, return an empty list
  with "no_condition": true.
- If an exposure exists but no candidate fits, return an empty list with
  "other": true and put a short free-text label in "suggested_label".
- "other" and "no_condition" are mutually exclusive and must not be combined
  with selected terms.

Return JSON: {{"terms": [{{"term_id": "PECO:...", "label": "...", "evidence": "..."}}], "no_condition": false, "other": false, "suggested_label": null}}
"""


def _load_index(index_dir):
    index = Path(index_dir)
    terms = json.loads((index / "terms.json").read_text())
    synonyms = json.loads((index / "synonyms.json").read_text())
    embeddings = np.load(index / "embeddings.npy")
    return terms, synonyms, embeddings


def _query_text(biosample, sra, summary):
    return "\n".join(evidence_lines(biosample, sra, summary))


def _lexical_hits(query_text, synonyms, allowed_ids):
    lowered = query_text.lower()
    hits = []
    for phrase, term_ids in synonyms.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            hits.extend(term_id for term_id in term_ids if term_id in allowed_ids)
    return list(dict.fromkeys(hits))


def _candidates(query_text, synonyms, terms, embeddings, model, top_k, allowed_ids):
    indices = [i for i, term in enumerate(terms) if term["id"] in allowed_ids]
    if not indices:
        raise RuntimeError("the PECO index has no plant exposure terms")

    query = model.encode([query_text], normalize_embeddings=True)[0].astype("float32")
    scores = embeddings[indices] @ query
    max_score = float(scores.max()) if scores.size else 0.0

    term_by_id = {term["id"]: term for term in terms}
    selected = []
    seen = set()

    for term_id in _lexical_hits(query_text, synonyms, allowed_ids):
        if term_id in term_by_id and term_id not in seen:
            selected.append(term_by_id[term_id])
            seen.add(term_id)
            if len(selected) >= top_k:
                return selected, max_score

    for offset in np.argsort(-scores):
        term = terms[indices[int(offset)]]
        if term["id"] in seen:
            continue
        selected.append(term)
        seen.add(term["id"])
        if len(selected) >= top_k:
            break
    return selected, max_score


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def _validate(parsed, candidate_ids, term_by_id):
    terms = parsed.get("terms")
    if not isinstance(terms, list):
        raise ValueError("response has no 'terms' list")

    cleaned = []
    for item in terms:
        if not isinstance(item, dict):
            raise ValueError("term entries must be objects")
        term_id = str(item.get("term_id", "")).strip()
        if term_id not in candidate_ids:
            raise ValueError(f"term_id {term_id!r} is not in the candidate list")
        evidence = str(item.get("evidence", "")).strip()
        if not evidence:
            raise ValueError(f"term {term_id} has no evidence")
        cleaned.append(
            {
                "term_id": term_id,
                "label": term_by_id[term_id]["label"],
                "evidence": evidence,
            }
        )

    no_condition = _as_bool(parsed.get("no_condition", False))
    other = _as_bool(parsed.get("other", False))
    suggested = parsed.get("suggested_label")
    suggested = suggested.strip() if isinstance(suggested, str) else ""

    if other and no_condition:
        raise ValueError("'other' and 'no_condition' cannot both be true")
    if other and cleaned:
        raise ValueError("'other' cannot be combined with selected terms")
    if not cleaned and not (other or no_condition):
        raise ValueError("empty terms list without other=true or no_condition=true")
    if not other:
        suggested = ""
    return cleaned, no_condition, other, suggested


from script_logging import setup as _setup

LOGGER = _setup("label_exposure")


def _label_one(
    samn, runs, inputs, params, model, terms, synonyms, embeddings, ancestors
):
    """Label one run's exposure terms; returns the result dict or None."""
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

    allowed_ids = {term["id"] for term in terms if term.get("branch") == "exposure"}
    top_k = int(params["top_k"])
    query_text = _query_text(biosample, sra, summary)
    sample_lines, project_lines = exposure_evidence(biosample, sra, summary)
    candidates, max_score = _candidates(
        query_text, synonyms, terms, embeddings, model, top_k, allowed_ids
    )
    candidate_ids = {term["id"] for term in candidates}
    term_by_id = {term["id"]: term for term in terms}

    prompt = PROMPT.format(
        sample_evidence="\n".join(sample_lines) or "(none)",
        project_evidence="\n".join(project_lines) or "(none)",
        candidates="\n".join(
            f"- {term['id']} | {term['label']} | {term['definition'][:300]}"
            for term in candidates
        ),
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]

    last_error = None
    selected = None
    no_condition = False
    other = False
    suggested_label = ""
    for _ in range(3):
        try:
            selected, no_condition, other, suggested_label = _validate(
                chat_json(
                    params["server_url"],
                    params["api_key"],
                    params["model"],
                    messages,
                    params["model_params"],
                    max_tokens=int(params.get("max_tokens", 2048)),
                ),
                candidate_ids,
                term_by_id,
            )
            break
        except ValueError as error:
            last_error = error
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The previous response was invalid: {error}. "
                        "Return valid JSON using only candidate term IDs."
                    ),
                }
            )

    if selected is None:
        raise RuntimeError(f"could not label {samn}: {last_error}")

    selected, pruned = prune_ancestors(selected, ancestors)

    result = {
        "biosample": samn,
        "run": runs[0] if runs else None,
        "layer": "exposure",
        "model": params["model"],
        "n_candidates": len(candidates),
        "no_condition": no_condition,
        "other": other,
        "suggested_label": suggested_label,
        "max_retrieval_score": round(max_score, 4),
        "pruned_ancestors": pruned,
        "terms": selected,
        "query": query_text,
    }

    LOGGER.info(
        "%s: %d exposure terms (no_condition=%s, other=%s, max_score=%s, pruned=%d)",
        samn,
        len(selected),
        no_condition,
        other,
        max_score,
        len(pruned),
    )
    output = Path(inputs["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    params = dict(snakemake.params)
    terms, synonyms, embeddings = _load_index(snakemake.input.index)
    # The encoder is the expensive per-job constant; load it once per chunk.
    model = SentenceTransformer(params["embed_model"])
    ancestors = ancestor_map(terms)
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
                "output": f"results/exposure/{samn}.json",
            },
            params,
            model,
            terms,
            synonyms,
            embeddings,
            ancestors,
        )

    def stub(item, error):
        samn, runs, _ = item
        return {
            "biosample": samn,
            "run": runs[0] if runs else None,
            "layer": "exposure",
            "source": "error",
            "error": error,
            "no_condition": False,
            "other": True,
            "suggested_label": "",
            "terms": [],
            "max_retrieval_score": None,
        }

    run_chunk(
        items,
        lambda item: f"results/exposure/{item[0]}.json",
        process,
        stub,
        snakemake.output[0],
        LOGGER,
    )


if __name__ == "__main__":
    main()
