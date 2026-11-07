# AGENTS.md

This repository has three independent Python projects: the Snakemake workflow
at the repository root (`workflow/`, `config/`, `.test/`), the Streamlit review
app in `review_app/`, and the original LlamaIndex RAG CLI in `src/`. The RAG CLI
has no tests or packaging; the Snakemake workflow and review app have
lint/format/test checks in CI.

## Running

- Entrypoint: `src/custom_rag_cli.py`. Invoke it with an interpreter that has
  the conda env from `setup.yaml`; the shebang is a hardcoded Savio/GCP path
  (`/global/scratch/users/milesroberts/envs/ollama/bin/python`) and the local
  `python3` does not have `llama_index`.
- Ollama must already be running (`ollama serve`), with the requested model
  pulled. No host is configured in code, so the LlamaIndex Ollama client uses
  its default `http://localhost:11434`.
- `--files` is a directory, not a file. The README example uses `papers/`, but
  that directory is not checked in, so it must exist and contain PDFs first.
- `context_window=1024` is set intentionally in `custom_rag_cli.py` to limit
  memory. Do not raise it without a reason.
- The Click decorator above `main()` is separated from it by commented-out
  `cli` code. It still decorates `main`, and `main()` at the bottom is the
  Click entrypoint; do not "clean up" that block without rewiring the CLI.

## Paper retrieval

- `src/retrive_k-mer_papers.py` is a separate script, not part of the RAG CLI.
  It requires the `pypaperretriever` package in its Python environment,
  searches PubMed, downloads PDFs into `PDFs/`, and extracts images. It makes
  live network calls and writes files; only run it intentionally. No
  environment file for it is checked in.
- Filename and env spellings (`retrive`, `pypaperretriver`) are inconsistent.
  Keep existing paths unless you are deliberately renaming them.

## Snakemake workflow

- The workflow is at the repository root; run commands from the repo root
  (`config/`, `workflow/`, `results/`).
- Directory convention: `config/` holds curated inputs (config, sample sheet),
  `resources/` is reserved for manually curated uploads and stays empty, and
  everything the workflow fetches or generates lives under `results/`
  (`results/metadata/` for API fetches, `results/peco/` for the ontology and
  index). Do not route machine fetches back into `resources/`.
- Before committing changes under `workflow/`, `config/`, or `.test/`, run
  `snakefmt --check workflow/` and `scripts/lint-snakemake.sh` (the lint
  wrapper that ignores the log-directive advisory; see below). For Python
  sources run
  `ruff check` and `ruff format --check`. Pre-commit hooks do this locally and
  `.github/workflows/sra-peco-ci.yml` repeats it on push/PR.
- The Snakemake workflow catalog only discovers `Snakefile` or
  `workflow/Snakefile` at the repository root. Do not move the workflow back
  under a subdirectory without updating the catalog layout.
- Models are served locally by Ollama on the Savio H200 node (`qwen3.8`,
  `tev1:4b`), not by Ollama Cloud. `workflow/savio/run.sh` starts the shared
  model-server job and points workers at it. Slurm job logs live only in
  `.snakemake/slurm_logs/` (the plugin's default); do not add `log:` directives
  back to rules, and write script progress with the shared `script_logging`
  logger so messages land in those job logs.
- Savio sync is git-only: never scp/rsync repository files to Savio. Commit
  and push locally, then `git pull` in the scratch clone.
- Tissue, germplasm, and the two PECO layers use `OTHER`/`unknown` sentinels
  plus review flags in `results/labels.tsv`; see `README.md` and
  `config/README.md` for thresholds and setup.
- `fetch_sra_metadata` is required for germplasm classification: mutant and
  transgenic signals often live in the SRA experiment title or library name,
  not in the BioSample record.
- `classify_rna_type` is a hard inclusion filter before labeling. Only
  `accepted_rna_types` reach `results/labels.tsv`; all others go to
  `results/labels.excluded.tsv`. The four label rules short-circuit with a
  stub for excluded runs, so keep their `rna_type` input wired.
- `fetch_bioprojects` supplies the BioProject metadata shown in the review app.
  Do not remove it from `rule all` without checking the app's fallback.
- `fetch_athrdb` is a single serial job with an ATHRDB rate limit
  (`athrdb.min_interval_seconds` / `athrdb.jitter_fraction` /
  `athrdb.max_requests`), fetched by its own target `snakemake athrdb_all`
  (never part of `rule all`, never gating labels). Jitter is one-sided and never shortens a gap below
  `min_interval_seconds`. It is evidence-only and fail-soft: query failures
  become `athrdb_note` stubs, never workflow errors. Do not turn it into
  per-run jobs; that multiplies request pressure. It is NOT an input to the
  tissue/germplasm labelers (that gated whole windows behind the serial
  fetch); aggregate cross-checks it against the labels and flags
  `athrdb_disagreement` for review instead.
- ENA-origin accessions (ERR/SAMEA/PRJEB) work via NCBI mirrors, with ENA
  fallbacks: `SAMEA…` BioSample records come from ENA's XML API, and runs that
  NCBI `efetch db=sra` silently omits are refetched from ENA `filereport`
  (`fetch_source: "ena"`). A run missing from both mirrors is stored as a
  stub (`fetch_source: "missing"`), never a window failure.
  ATHRDB has no coverage for ENA-only libraries (no GEO record); expect
  `no_geo_record` stubs there.
- Window batching (`batch_size`/`batch_index`) slices the sheet per
  invocation; each window writes `results/rows/{window}-{chunk}.tsv` fragments
  and `aggregate` only concatenates them (newest window wins per run), so
  `labels.tsv` accumulates without rescanning per-run metadata. The fragments
  are the source of truth: deleting `results/rows/` forces a full rebuild. The single-job metadata
  fetchers skip existing outputs, which makes repeated windows and later
  windows safe; ATHRDB `request_cap_reached` stubs are retried when budget
  remains. Keep `batch_size` ≤ `athrdb.max_requests`.
- The five labeling rules (RNA type, tissue, germplasm, exposure, study
  condition) are keyed by BioSample and run in chunk jobs of
  `label_chunk_size` samples (default 50; exposure uses `exposure_chunk_size`,
  default 25), not one job per sample. All runs of a
  sample are pooled as evidence; per-sample output paths are unchanged in
  shape (`results/{kind}/{samn}.json`), and `labels.tsv` keeps one row per
  run. Per-run keying gave runs of one sample different exposure term sets
  (87% of multi-run samples), so do not reintroduce it. A failed chunk redoes
  up to `label_chunk_size` samples, and samples whose output already
  exists are skipped, so a retried chunk only redoes the tail.
- Labeler chunks are fail-soft: a sample the model cannot label gets a
  stub (`source: "error"`) plus review flags instead of failing the
  chunk, and the marker records `written`/`skipped`/`failures`.
  `llm.chat_json` escalates `num_predict` once when Ollama reports
  `done_reason: "length"` (truncated JSON) before raising
  `TruncatedResponse`.
- Tissue and germplasm rules read structured attribute fields only
  (`tissue.rule_attribute_keys` / `germplasm.rule_attribute_keys`); study
  titles/abstracts, library names, and experiment titles are model evidence,
  never rule evidence. ENA `plant structure` values carry Plant Ontology IDs
  that map via `tissue.po_terms` (e.g. `PO:0025034` → leaf). Do not loosen
  these back to full-text matching — it produced the false
  natural-accession, false transgenic, and false cell-culture labels in the
  first two windows.
- The Ollama server job checks both `qwen3.8` and `tev1:4b` at startup; a
  missing decision model aborts the job instead of silently 404ing every
  `/v1/systemone` call and falling back to chat for the whole window.
- The exposure prompt splits per-sample evidence from project-level context
  (study abstract, paper conditions): terms must be grounded in per-sample
  evidence, project text only disambiguates. This stops replicate noise like
  window 3's `Warm_T_1/2/3` replicates receiving different term sets.

- Gene quantification is a second target: `snakemake quant_all`, never part of
  `rule all`. The DAG shape depends on library layout, so run
  `python workflow/scripts/quant_prepare.py` first; it writes
  `results/quant/targets.tsv`. Runs of a BioSample share one Salmon run (pooled
  FASTQs), except the ~157 mixed-layout samples, which fall back to per-run
  quant. `fastp` must never pass `--dedup` (RNA-seq duplicates are biological).
  SE libraries use Salmon's defaults `--fldMean 250 --fldSD 25`.

- Thread counts live in `workflow/profiles/default/config.yaml` (`set-threads`:
  8 for Salmon/fastp, 4 for TIN) together with per-rule memory and runtimes;
  rules only use `{threads}`. Never reintroduce thread counts in `config.yaml`
  or `params`, and never add `cpus_per_task` to `default-resources` — the Slurm
  plugin derives it from `set-threads`. `default-resources` keeps `mem_mb: 0`
  because Savio's HTC partitions derive memory from the CPU count — any other
  value would be a second, conflicting request. Quantification is invoked with
  `--jobs 4 --cores 32`: `--cores` must cover the largest thread request or
  Snakemake clamps it, and `--jobs` sets concurrency. Trimming and Salmon share
  one job per sample, raw FASTQs are `temp()`, fastp reports live inside the
  sample's quant directory, and trimmed reads are deleted when the job succeeds.

## Review app

- `review_app/` is a Streamlit app backed by SQLite at
  `results/review/review.db`. It reads `results/labels.tsv` and the fetched
  caches under `results/metadata/`; it must never modify `labels.tsv`.
- Start it with `bash review_app/run.sh`, or
  `streamlit run review_app/app.py`. Export with
  `python -m review_app.export`.
- SQLite assumes one shared app process. Do not run multiple app hosts against
  the same database on a network filesystem.
- Reviewer names are self-declared, not authenticated. Do not describe the
  event log as compliance-grade attribution.
- After changing the app or its data layer, run
  `pytest -q review_app/tests workflow/tests` and
  `ruff check review_app workflow/scripts workflow/tests`.

## Session transcripts

- Before every `git push`, run `scripts/export-session.sh <session-name>` and
  commit the new `transcripts/*.json.xz` with that push. The script uses
  `OPENCODE_SESSION_ID` for the current session.
- The default export is complete; `--sanitize` redacts tool inputs and outputs
  and should only be used when the transcript leaves the repo.

## Environment files

- `setup.yaml` is a `conda env export` snapshot with a hardcoded `prefix:`
  value for the Berkeley Savio cluster. Treat it as a reproducible spec for
  that cluster, not a portable lockfile.
- Verification is end-to-end: run the CLI against a small PDF directory with
  Ollama and the model available. There is no faster test target.
