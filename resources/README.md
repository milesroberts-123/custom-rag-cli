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

## Files

- `SraRunInfo.csv` (2026-11-03, downloaded from NCBI SRA Run Selector's
  "Data access: RunInfo Table") — one row per SRA run (SRR), 136,608 runs.
  Run-level download and library metadata: run, experiment, library strategy/
  selection/source, BioProject, BioSample, sample name, taxon, spots, bases.
- `sra_result.csv` (2026-11-03, downloaded from NCBI SRA search results) —
  one row per experiment (SRX), 119,002 rows. Experiment-level metadata:
  experiment title, organism, instrument, submitter, study accession/title,
  sample accession/title, total size/spots/bases.
- `peco.owl`, `peco_index/`, `sra/`, `biosample/`, `bioproject/`, `paper/` —
  legacy workflow-fetch caches from before the directory convention changed
  (fetched data now lives under `results/`); pending migration on Savio.

`notebooks/conditional_expression.Rmd` merges the two SRA tables into
`results/sra_merged.csv`.