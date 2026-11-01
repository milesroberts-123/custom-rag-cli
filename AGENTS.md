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
  It uses the `pypaperretriever` environment (`pypaperretriever.yaml`), searches
  PubMed, downloads PDFs into `PDFs/`, and extracts images. It makes live
  network calls and writes files; only run it intentionally.
- Filename and env spellings (`retrive`, `pypaperretriver`) are inconsistent.
  Keep existing paths unless you are deliberately renaming them.

## Snakemake workflow

- The workflow is at the repository root; run commands from the repo root
  (`config/`, `workflow/`, `results/`, `resources/`).
- Before committing changes under `workflow/`, `config/`, or `.test/`, run
  `snakefmt --check workflow/` and `snakemake --lint`. For Python sources run
  `ruff check` and `ruff format --check`. Pre-commit hooks do this locally and
  `.github/workflows/sra-peco-ci.yml` repeats it on push/PR.
- The Snakemake workflow catalog only discovers `Snakefile` or
  `workflow/Snakefile` at the repository root. Do not move the workflow back
  under a subdirectory without updating the catalog layout.
- Models are served locally by Ollama on the Savio H200 node (`qwen3.8`,
  `tev1:4b`), not by Ollama Cloud. `workflow/savio/run.sh` starts the shared
  model-server job and points workers at it.
- Tissue, germplasm, and the two PECO layers use `OTHER`/`unknown` sentinels
  plus review flags in `results/labels.tsv`; see `README.md` and
  `config/README.md` for thresholds and setup.
- `fetch_sra_metadata` is required for germplasm classification: mutant and
  transgenic signals often live in the SRA experiment title or library name,
  not in the BioSample record.
- `fetch_bioprojects` supplies the BioProject metadata shown in the review app.
  Do not remove it from `rule all` without checking the app's fallback.

## Review app

- `review_app/` is a Streamlit app backed by SQLite at
  `results/review/review.db`. It reads `results/labels.tsv` and `resources/`;
  it must never modify `labels.tsv`.
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

- `setup.yaml` and `pypaperretriever.yaml` are `conda env export` snapshots with
  hardcoded `prefix:` values for the Berkeley Savio cluster. Treat them as
  reproducible specs for that cluster, not portable lockfiles.
- Verification is end-to-end: run the CLI against a small PDF directory with
  Ollama and the model available. There is no faster test target.
