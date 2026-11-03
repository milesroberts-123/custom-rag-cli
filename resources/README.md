# resources/

This directory is reserved for manually curated data that you upload yourself:
reference files, hand-maintained tables, or anything prepared outside this
workflow.

Everything the workflow fetches or generates lives under `results/`:

- `results/metadata/` — NCBI, Europe PMC, BioProject, and PlantRNADB fetches
- `results/peco/` — the downloaded PECO ontology and its embedding index
- other `results/` subdirectories — per-run classifications and the final
  label tables

Nothing in this directory is consumed by any rule yet. Add files here only if
you intend to curate them by hand.