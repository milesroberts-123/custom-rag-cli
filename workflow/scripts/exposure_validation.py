"""Validation for the exposure labeler's JSON response.

Kept free of heavy imports so it can be unit tested without loading the
sentence-transformer stack. The model occasionally returns contradictory flags
(``other`` next to grounded terms, or ``other`` together with ``no_condition``);
those are resolved deterministically here instead of failing the sample, because
one contradictory response should not cost a BioSample its exposure label.
"""


def as_bool(value):
    """Parse the truthy spellings the model emits for boolean fields."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def validate_exposure_response(parsed, candidate_ids, term_by_id):
    """Validate one model response and resolve contradictory flags.

    Returns ``(terms, no_condition, other, suggested_label, conflicts)`` where
    ``conflicts`` names each contradiction that was resolved. Raises
    ``ValueError`` only for responses that cannot be salvaged (bad term IDs,
    missing evidence, or an entirely empty result).
    """
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

    no_condition = as_bool(parsed.get("no_condition", False))
    other = as_bool(parsed.get("other", False))
    suggested = parsed.get("suggested_label")
    suggested = suggested.strip() if isinstance(suggested, str) else ""

    conflicts = []
    if cleaned:
        # Grounded terms outrank both negative flags: they carry evidence, the
        # flags are claims about absence.
        if other:
            conflicts.append("other_with_terms")
        if no_condition:
            conflicts.append("no_condition_with_terms")
        other = False
        no_condition = False
    elif other and no_condition:
        # Neither is grounded. Keep the weaker claim (an unlisted condition)
        # rather than asserting the sample was untreated.
        conflicts.append("other_and_no_condition")
        no_condition = False

    if not cleaned and not (other or no_condition):
        raise ValueError("empty terms list without other=true or no_condition=true")
    if not other:
        suggested = ""
    return cleaned, no_condition, other, suggested, conflicts
