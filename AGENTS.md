# AGENTS.md

This repository has two independent Python projects: the original LlamaIndex
RAG CLI in `src/`, and the Snakemake workflow in `sra-peco/`. The RAG CLI has no
tests or packaging; the Snakemake workflow has lint/format checks in CI.

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

## sra-peco workflow

- `sra-peco/` is a self-contained Snakemake 9 workflow; run commands from that
  directory (`config/`, `workflow/`, `results/`, `resources/`).
- Before committing changes under `sra-peco/`, run `snakefmt --check workflow/`
  and `snakemake --lint`. Pre-commit hooks do this locally and
  `.github/workflows/sra-peco-ci.yml` repeats it on push/PR.
- Models are served locally by Ollama on the Savio H200 node (`qwen3.8`,
  `tev1:4b`), not by Ollama Cloud. `workflow/savio/run.sh` starts the shared
  model-server job and points workers at it.
- Tissue and PECO outputs use an `OTHER` sentinel plus review flags in
  `results/labels.tsv`; see `sra-peco/README.md` for thresholds and setup.

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
