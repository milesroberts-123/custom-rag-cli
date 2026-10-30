"""Summarize the experimental conditions described in a paper once per project."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from llm import chat_json, make_client

SYSTEM = (
    "You are a plant molecular biologist extracting experimental conditions "
    "from a paper. Return only a JSON object."
)

PROMPT = """Read this excerpt from the paper associated with BioProject {prjna}.

Extract the experimental conditions that apply to the RNA-seq samples. Return a
JSON object with exactly these keys:
- "genotype": string or null
- "treatment": string or null
- "growth_conditions": string or null
- "tissue_sampled": string or null
- "stress": string or null
- "evidence": short direct quote(s) supporting the values, string

Do not invent details that are not in the excerpt. Use null when unknown.

Excerpt:
{excerpt}
"""

METHOD_RE = re.compile(r"method|material|experimental|procedure", re.IGNORECASE)
CONDITION_KEYS = (
    "genotype",
    "treatment",
    "growth_conditions",
    "tissue_sampled",
    "stress",
)


def _strip_namespaces(xml_text):
    return re.sub(r'\sxmlns(:[\w-]+)?="[^"]*"', "", xml_text)


def _text(element):
    return " ".join("".join(element.itertext()).split())


def _jats_excerpt(xml_text, max_chars):
    root = ET.fromstring(_strip_namespaces(xml_text))
    parts = []

    title = root.find(".//article-title")
    if title is not None:
        parts.append(("title", _text(title)))

    abstract = root.find(".//abstract")
    if abstract is not None:
        parts.append(("abstract", _text(abstract)))

    for section in root.findall(".//sec"):
        heading = section.find("title")
        sec_type = (section.get("sec-type") or "").lower()
        matches_heading = heading is not None and METHOD_RE.search(_text(heading))
        if matches_heading or "method" in sec_type:
            parts.append(("methods", _text(section)))

    captions = [_text(c) for c in root.findall(".//table-wrap/caption")]
    captions += [_text(c) for c in root.findall(".//fig/caption")]
    if captions:
        parts.append(("captions", " ".join(captions)))

    if not any(name == "methods" for name, _ in parts):
        body = root.find(".//body")
        if body is not None:
            parts.append(("body", _text(body)))

    chunks = []
    total = 0
    for name, text in parts:
        if not text:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        excerpt = text[:remaining]
        chunks.append(f"[{name}]\n{excerpt}")
        total += len(excerpt)
    return "\n\n".join(chunks)


def _normalize(parsed):
    conditions = {}
    for key in CONDITION_KEYS:
        value = parsed.get(key)
        conditions[key] = value.strip() if isinstance(value, str) and value.strip() else None
    evidence = parsed.get("evidence")
    conditions["evidence"] = (
        evidence.strip() if isinstance(evidence, str) and evidence.strip() else ""
    )
    return conditions


def _summarize(client, model, model_params, prjna, excerpt):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": PROMPT.format(prjna=prjna, excerpt=excerpt)},
    ]
    last_error = None
    for _ in range(3):
        try:
            parsed = chat_json(client, model, messages, model_params)
            if isinstance(parsed, dict):
                return _normalize(parsed)
            last_error = ValueError("response was not a JSON object")
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
    raise RuntimeError(f"could not summarize {prjna}: {last_error}")


def main():
    with open(snakemake.input.paper) as handle:
        paper = json.load(handle)

    output = snakemake.output[0]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    prjna = paper["prjna"]

    if paper.get("status") == "none":
        result = {
            "prjna": prjna,
            "has_paper": False,
            "low_confidence": True,
            "conditions": None,
        }
    else:
        max_chars = int(snakemake.params.max_chars)
        if paper.get("status") == "fulltext" and paper.get("fulltext_xml"):
            try:
                excerpt = _jats_excerpt(paper["fulltext_xml"], max_chars)
                low_confidence = False
            except ET.ParseError:
                excerpt = (paper.get("abstract") or "")[:max_chars]
                low_confidence = True
        else:
            excerpt = (paper.get("abstract") or "")[:max_chars]
            low_confidence = True

        client = make_client(snakemake.params.server_url, snakemake.params.api_key)
        conditions = _summarize(
            client,
            snakemake.params.model,
            snakemake.params.model_params,
            prjna,
            excerpt,
        )
        result = {
            "prjna": prjna,
            "has_paper": True,
            "pmid": paper.get("pmid"),
            "low_confidence": low_confidence,
            "conditions": conditions,
        }

    with open(output, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
