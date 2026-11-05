"""PECO term helpers shared by labelers and tests (no heavy imports)."""


def ancestor_map(terms):
    """Return a term_id -> set-of-ancestors closure for the given terms."""
    known = {term["id"] for term in terms}
    parents = {
        term["id"]: [p for p in (term.get("parents") or []) if p in known]
        for term in terms
    }

    def ancestors(term_id):
        seen = set()
        stack = list(parents.get(term_id, []))
        while stack:
            parent = stack.pop()
            if parent in seen:
                continue
            seen.add(parent)
            stack.extend(parents.get(parent, []))
        return seen

    return ancestors


def prune_ancestors(selected, ancestors):
    """Drop selected terms that are ancestors of another selected term."""
    ids = {term["term_id"] for term in selected}
    drop = {
        term_id
        for term in selected
        for term_id in ancestors(term["term_id"])
        if term_id in ids
    }
    kept = [term for term in selected if term["term_id"] not in drop]
    return kept, sorted(drop)
