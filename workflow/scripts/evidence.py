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


def _fmt_number(value):
    """Format a numeric paper field without a trailing .0."""
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


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
    day_length = conditions.get("day_length_hours")
    if isinstance(day_length, (int, float)):
        lines.append(f"paper_day_length_hours: {_fmt_number(day_length)}")
    temperature = conditions.get("growth_temperature_c")
    if isinstance(temperature, (int, float)):
        lines.append(f"paper_growth_temperature_c: {_fmt_number(temperature)}")
    if conditions.get("evidence"):
        lines.append(f"paper_evidence: {conditions['evidence'][:500]}")
    return lines


def merge_sra(records):
    """Merge the SRA records of several runs that belong to one BioSample.

    A BioSample can be sequenced as more than one run. Sample-level fields are
    identical across those runs, but experiment title and library name can
    differ; they are joined so the labeler sees every value instead of an
    arbitrary one. ``aggregate`` flags samples whose runs disagree on those
    fields for review.
    """
    merged = {}
    joined = ("experiment_title", "library_name", "sample_name")
    for record in records:
        for key, value in (record or {}).items():
            if key in joined:
                if not value:
                    continue
                values = [part for part in (merged.get(key) or "").split("; ") if part]
                if value not in values:
                    values.append(value)
                merged[key] = "; ".join(values)
            elif key == "sample_attributes":
                attributes = dict(merged.get(key) or {})
                for name, attribute in (value or {}).items():
                    if attribute and not attributes.get(name):
                        attributes[name] = attribute
                merged[key] = attributes
            elif value and not merged.get(key):
                merged[key] = value
    return merged


def exposure_evidence(biosample, sra, summary, max_abstract=800):
    """Split exposure evidence into per-sample and project-level blocks.

    The exposure labeler needs the split so the model cannot ground a term
    solely in project-level text (study abstract, paper conditions): that
    produced replicate noise in window 3, where identical-condition replicates
    received different term sets drawn from the same abstract.
    """
    sample = attribute_lines(biosample.get("attributes", {}))
    organism = biosample.get("organism")
    if organism:
        sample.append(f"organism: {organism}")
    for key in ("experiment_title", "library_name", "sample_name"):
        value = sra.get(key)
        if value:
            sample.append(f"{key}: {value}")
    for name, value in sorted((sra.get("sample_attributes") or {}).items()):
        if value:
            sample.append(f"sra_{name}: {value}")

    project = []
    study_title = sra.get("study_title")
    if study_title:
        project.append(f"study_title: {study_title}")
    abstract = sra.get("study_abstract")
    if abstract:
        project.append(f"study_abstract: {abstract[:max_abstract]}")
    project.extend(paper_lines(summary))
    return sample, project


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
