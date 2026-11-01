"""Turn BioSample, SRA, and paper records into compact prompt evidence."""

PAPER_KEYS = ("genotype", "treatment", "growth_conditions", "tissue_sampled", "stress")


def attribute_lines(attributes, keys=None):
    """Return selected ``name: value`` lines from a BioSample attribute dict."""
    lines = []
    for name, value in sorted((attributes or {}).items()):
        if keys and not any(key.lower() in name.lower() for key in keys):
            continue
        if value:
            lines.append(f"{name}: {value}")
    return lines


def sra_lines(sra, max_abstract=800):
    """Return experiment, library, sample, and study context from an SRA record."""
    lines = []
    for key in ("experiment_title", "library_name", "sample_name", "study_title"):
        value = sra.get(key)
        if value:
            lines.append(f"{key}: {value}")
    abstract = sra.get("study_abstract")
    if abstract:
        lines.append(f"study_abstract: {abstract[:max_abstract]}")
    for name, value in sorted((sra.get("sample_attributes") or {}).items()):
        if value:
            lines.append(f"sra_{name}: {value}")
    return lines


def paper_lines(summary):
    """Return paper condition lines when a summarized paper is available."""
    if not summary.get("has_paper"):
        return []
    conditions = summary.get("conditions") or {}
    lines = []
    for key in PAPER_KEYS:
        value = conditions.get(key)
        if value:
            lines.append(f"paper_{key}: {value}")
    if conditions.get("evidence"):
        lines.append(f"paper_evidence: {conditions['evidence'][:500]}")
    return lines


def evidence_lines(biosample, sra, summary, attribute_keys=None, max_abstract=800):
    """Combine and deduplicate evidence lines for one run."""
    lines = attribute_lines(biosample.get("attributes", {}), attribute_keys)
    organism = biosample.get("organism")
    if organism:
        lines.append(f"organism: {organism}")
    lines.extend(sra_lines(sra, max_abstract=max_abstract))
    lines.extend(paper_lines(summary))

    seen = set()
    unique = []
    for line in lines:
        key = line.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(line)
    return unique
