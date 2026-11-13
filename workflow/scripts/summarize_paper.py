"""Summarize the experimental conditions described in a paper once per project."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from evidence import PAPER_KEYS
from llm import chat_json

SYSTEM = (
    "You are a plant molecular biologist extracting experimental conditions "
    "from a paper. Return only a JSON object."
)

PROMPT_VERSION = 2

STUDY_SETTINGS = ("growth_chamber", "greenhouse", "field", "laboratory", "in_vitro")

PROMPT = """Read this excerpt from the paper associated with BioProject {prjna}.

Extract the experimental conditions that apply to the RNA-seq samples. Return a
JSON object with exactly these keys:
- "genotype": string or null
- "treatment": string or null
- "growth_conditions": string or null
- "tissue_sampled": string or null
- "stress": string or null
- "day_length_hours": hours of light per day as a number; for example 16 for a
  16 h light / 8 h dark cycle, 24 for constant light; null when not reported
- "growth_temperature_c": growth temperature in Celsius as a number; use the
  midpoint of a stated range; null when not reported
- "study_setting": where the plants were grown, one of
  growth_chamber | greenhouse | field | laboratory | in_vitro; null when the
  excerpt does not say. Use growth_chamber for climate-controlled cabinets,
  rooms, or phytotrons; laboratory for in-vitro/plate/culture work; field for
  field sites or natural populations.
- "study_setting_quote": the exact sentence that states the setting, at most
  200 characters; null when study_setting is null
- "evidence": short direct quote(s) supporting the values, string

Do not invent details that are not in the excerpt. Use null when unknown.

Excerpt:
{excerpt}
"""

METHOD_RE = re.compile(r"method|material|experimental|procedure", re.IGNORECASE)


def _strip_namespaces(xml_text):
    return re.sub(r'\sxmlns(:[\w-]+)?="[^"]*"', "", xml_text)


def _text(element):
    return " ".join("".join(element.itertext()).split())


def _jats_excerpt(xml_text, max_chars):
    root = ET.fromstring(_strip_namespaces(xml_text))
    parts = []

    # Methods first: the growth setting and photoperiod live there, and the
    # excerpt budget is finite.
    for section in root.findall(".//sec"):
        heading = section.find("title")
        sec_type = (section.get("sec-type") or "").lower()
        matches_heading = heading is not None and METHOD_RE.search(_text(heading))
        if matches_heading or "method" in sec_type:
            parts.append(("methods", _text(section)))

    abstract = root.find(".//abstract")
    if abstract is not None:
        parts.append(("abstract", _text(abstract)))

    title = root.find(".//article-title")
    if title is not None:
        parts.append(("title", _text(title)))

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


def _as_number(value):
    """Coerce a prompt value to a float, or None when it is not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize(parsed):
    conditions = {}
    for key in PAPER_KEYS:
        value = parsed.get(key)
        conditions[key] = (
            value.strip() if isinstance(value, str) and value.strip() else None
        )

    setting = (conditions.get("study_setting") or "").strip().lower()
    quote = parsed.get("study_setting_quote")
    quote = quote.strip() if isinstance(quote, str) else ""
    if setting not in STUDY_SETTINGS or not quote:
        # A setting without a verbatim quote is not usable as evidence, and an
        # unknown label cannot be mapped to a PECO term.
        setting = None
        quote = ""
    conditions["study_setting"] = setting
    conditions["study_setting_quote"] = quote[:200]
    conditions["day_length_hours"] = _as_number(parsed.get("day_length_hours"))
    conditions["growth_temperature_c"] = _as_number(parsed.get("growth_temperature_c"))
    evidence = parsed.get("evidence")
    conditions["evidence"] = (
        evidence.strip() if isinstance(evidence, str) and evidence.strip() else ""
    )
    return conditions


def _summarize(server_url, api_key, model, model_params, prjna, excerpt):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": PROMPT.format(prjna=prjna, excerpt=excerpt)},
    ]
    last_error = None
    for _ in range(3):
        try:
            parsed = chat_json(
                server_url, api_key, model, messages, model_params, max_tokens=2048
            )
            if isinstance(parsed, dict):
                return _normalize(parsed)
            last_error = ValueError("response was not a JSON object")
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
    raise RuntimeError(f"could not summarize {prjna}: {last_error}")


from script_logging import setup as _setup

LOGGER = _setup("summarize_paper")


def main():
    with open(snakemake.input.paper) as handle:
        paper = json.load(handle)

    output = snakemake.output[0]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    prjna = paper["prjna"]

    if paper.get("status") in ("none", "error"):
        LOGGER.info(
            "%s: no usable publication (%s); writing stub",
            prjna,
            paper.get("status"),
        )
        result = {
            "prjna": prjna,
            "has_paper": False,
            "low_confidence": True,
            "text_source": None,
            "fetch_status": paper.get("status"),
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

        LOGGER.info(
            "%s: summarizing %d characters (%s)",
            prjna,
            len(excerpt),
            paper.get("status"),
        )
        conditions = _summarize(
            snakemake.params.server_url,
            snakemake.params.api_key,
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
            "text_source": "fulltext"
            if paper.get("status") == "fulltext"
            else "abstract",
            "prompt_version": PROMPT_VERSION,
            "conditions": conditions,
        }

    with open(output, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    LOGGER.info("%s: done (low_confidence=%s)", prjna, result["low_confidence"])


if __name__ == "__main__":
    main()
