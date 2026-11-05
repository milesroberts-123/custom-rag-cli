"""Build a lexical and embedding index over PECO terms."""

import json
import re
from pathlib import Path

import numpy as np
from pronto import Ontology
from sentence_transformers import SentenceTransformer


def _definition(term):
    definition = term.definition
    if not definition:
        return ""
    text = getattr(definition, "description", None) or str(definition)
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", text).strip()


def _synonyms(term):
    values = set()
    for synonym in term.synonyms:
        text = getattr(synonym, "description", None) or str(synonym)
        text = re.sub(
            r"\s*\((?:exact|narrow|broad|related)\)\s*$",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        if text:
            values.add(text)
    return sorted(values)


def _synonym_map(terms):
    mapping = {}
    for term in terms:
        for phrase in [term["label"], *term["synonyms"]]:
            key = phrase.strip().lower()
            if len(key) < 4:
                continue
            mapping.setdefault(key, []).append(term["id"])
    return mapping


def _descendant_ids(ontology, root_id):
    root = ontology[root_id]
    return {term.id for term in root.subclasses()} - {root_id}


def main():
    ontology = Ontology(snakemake.input[0])
    exposure_ids = _descendant_ids(ontology, snakemake.params.exposure_branch)
    study_ids = _descendant_ids(ontology, snakemake.params.study_branch)
    growth_ids = _descendant_ids(ontology, snakemake.params.growth_system_root)
    for root in snakemake.params.growth_system_extra_roots:
        growth_ids |= _descendant_ids(ontology, root)

    terms = []
    for term in ontology.terms():
        if not term.id.startswith("PECO:") or term.obsolete or not term.name:
            continue
        definition = _definition(term)
        synonyms = _synonyms(term)
        text = ". ".join(
            part for part in (term.name, definition, "; ".join(synonyms)) if part
        )
        if term.id in study_ids:
            branch = "study_condition"
        elif term.id in exposure_ids:
            branch = "exposure"
        else:
            branch = "other"
        terms.append(
            {
                "id": term.id,
                "label": term.name,
                "definition": definition,
                "synonyms": synonyms,
                "branch": branch,
                "growth_system": term.id in growth_ids,
                "parents": sorted(
                    parent.id
                    for parent in term.superclasses(distance=1)
                    if parent.id != term.id
                ),
                "text": text,
            }
        )

    if not terms:
        raise RuntimeError("no PECO terms parsed from the ontology")

    model = SentenceTransformer(snakemake.params.embed_model)
    embeddings = model.encode(
        [term["text"] for term in terms],
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype("float32")

    output = Path(snakemake.output[0])
    output.mkdir(parents=True, exist_ok=True)
    serializable = [
        {key: value for key, value in term.items() if key != "text"} for term in terms
    ]
    (output / "terms.json").write_text(json.dumps(serializable, indent=2) + "\n")
    (output / "synonyms.json").write_text(
        json.dumps(_synonym_map(terms), indent=2) + "\n"
    )
    np.save(output / "embeddings.npy", embeddings)


if __name__ == "__main__":
    main()
