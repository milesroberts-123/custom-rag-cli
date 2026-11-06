# SRA PECO and tissue labeling workflow

Snakemake workflow that labels SRA RNA-seq samples with plant tissue categories,
germplasm types, and terms from the [Plant Experimental Conditions Ontology
(PECO)](https://www.ebi.ac.uk/ols4/ontologies/peco).

## Repository layout

| Path | Contents |
|---|---|
| `workflow/` | Snakefile, rules, scripts, environments, profiles, and Savio launchers |
| `config/` | Workflow configuration, configuration guide, and sample sheet |
| `review_app/` | Streamlit human-review app and SQLite audit store |
| `src/` | Original LlamaIndex RAG CLI; see `src/README.md` |
| `results/` | Everything the workflow produces: fetched metadata caches under `results/metadata/`, the PECO ontology and index under `results/peco/`, per-run classifications, and the final label tables |
| `resources/` | Empty by default; reserved for manually curated data uploaded by hand (see `resources/README.md`) |
| `logs/` | Legacy Slurm job logs; new jobs write to `.snakemake/slurm_logs/` |

## Pipeline

A methods-style narrative of the full workflow is in
[`methods.md`](methods.md).

1. Fetch BioProject, BioSample, and SRA metadata from NCBI.
2. Resolve each BioProject to a PubMed ID. Projects without a linked
   publication are skipped.
3. Fetch open-access full text (or the abstract) from Europe PMC.
4. Summarize the paper's experimental conditions once per BioProject.
5. Classify each run's RNA type; only mRNA and ribo-depleted total RNA
   continue.
6. Label each retained run's tissue category.
7. Classify each retained run's germplasm: natural accession, mutant,
   transgenic, hybrid, grafted, cell culture, polyploid, aneuploid, or unknown.
8. Label plant exposure PECO terms from the `PECO:0001001` branch.
9. Label the PECO plant study condition from the `PECO:0007231` branch.
10. Aggregate retained runs into `results/labels.tsv` and excluded runs into
    `results/labels.excluded.tsv`.

## Inputs

`config/samples.tsv` — one SRA run per row:

```tsv
run	biosample	bioproject	species
SRR41450469	SAMN64520521	PRJNA1552792	Arabidopsis thaliana
```

`config/config.yaml` — workflow parameters, including tissue categories,
germplasm patterns, model names, and review thresholds. See
[`config/README.md`](config/README.md) for the full configuration guide.

## Batched runs

Large sheets (e.g. every Arabidopsis run in `SraRunInfo.csv`) do not need to
be processed in one invocation. Two optional config keys slice the sheet into
a fixed order of non-overlapping windows:

```bash
--config batch_size=5000 batch_index=3   # rows 10001-15000 of the sheet
```

- **One sheet, many invocations.** Keep a single `samples_all.tsv` as
  `config.samples` (point to it via `--config samples=...`); the window keys
  select which rows each invocation processes. Rows are taken in sheet order,
  so windows are deterministic and non-overlapping: window *k* is rows
  `(k-1)*batch_size + 1` … `k*batch_size`. Unset keys (both 0, the default)
  process the whole sheet, which is what the `.test` catalog case uses.
- **`labels.tsv` accumulates through row fragments.** Each window writes one
  TSV fragment per chunk under `results/rows/{window}-{chunk}.tsv`, holding the
  final row for every run of that chunk (including excluded runs). `aggregate`
  concatenates the fragments, keeping the newest window's row per run, so its
  cost is proportional to the number of chunks rather than to every run on the
  sheet. Window 3's table therefore contains runs 1–15000, not just
  10001–15000. Runs classified but not fully labeled are reported as
  incomplete; rerun their window to finish them. Deleting `results/rows/`
  forces a full rebuild (the fragments are the source of truth for the table).
- **Fetches are window-bounded and repeat-safe.** The single-job metadata
  fetchers (NCBI, BioProject, paper, ATHRDB) process only the window's
  accessions and skip files that already exist, so later windows never
  re-query earlier windows' accessions. ATHRDB `request_cap_reached` stubs
  are retried automatically in a later window when request budget remains.
  Keep `batch_size` at or below `athrdb.max_requests` (default 5000) so no
  window needs a second pass.
- **Label jobs are chunked.** All five labeling rules — RNA type, tissue,
  germplasm, exposure, and study condition — process runs in chunk jobs of
  `label_chunk_size` runs (default 50) instead of one job per run: the
  Python interpreter and the sentence-transformer encoder load once per
  chunk, which removes most per-job startup overhead at window scale.
  Outputs are keyed by BioSample (`results/{rna_type,tissue,germplasm,
  exposure,study_condition}/{samn}.json`): a sample's annotations describe the
  biological material, and the runs of one sample share them. `labels.tsv`
  keeps one row per run, so the review app and downstream consumers are
  unchanged. Samples whose runs disagree on experiment title or library name
  are flagged `mixed_run_context` for review. Retry granularity is a chunk: a
  failed chunk redoes up to `label_chunk_size` samples. Exposure, the slowest
  layer, uses smaller chunks of `exposure_chunk_size` samples (default 25) so
  more of its jobs run concurrently. ATHRDB is fetched by its own target,
  `snakemake athrdb_all`, and never gates `rule all` or the labels.
- **On Savio**, batch through the launcher; extra arguments pass straight to
  Snakemake:

  ```bash
  bash workflow/savio/run.sh \
      --config samples=config/samples_all.tsv batch_size=5000 batch_index=1
  ```

  Each invocation starts its own four-H200 Ollama server job and cancels it on
  exit, so a batch sequence is just this command repeated with an increasing
  `batch_index`. The conda environments and PECO index are built once and
  reused. Window sizing rule of thumb: ATHRDB pacing (~2–2.5 s per new run)
  means a 5000-run window spends roughly 3 h in the serial fetch job.
- Preview a window without running anything with
  `snakemake -n --config batch_size=5000 batch_index=3` (job counts show the
  window's runs). `snakemake --batch RULE=K/N` is unrelated to this scheme
  and not used here; the config-key windows are what bounds the fetch rules.

## Models

The default stack runs against one local Ollama server:

| Step | Model | Endpoint |
|---|---|---|
| RNA type | `tev1:4b` | `/v1/systemone` (decision) |
| Tissue | `tev1:4b` | `/v1/systemone` (decision) |
| Germplasm | `tev1:4b` | `/v1/systemone` (decision) |
| Study condition | `tev1:4b` | `/v1/systemone` (decision) |
| Exposure | `qwen3.8` | `/api/chat` (native) |
| Paper summary | `qwen3.8` | `/api/chat` (native) |

Each decision step falls back to the chat model if the decision endpoint
fails. `config/config.yaml` sets `ollama.server_url` and `ollama.api_key`; the
`OLLAMA_SERVER` and `OLLAMA_API_KEY` environment variables override them.

Chat calls use Ollama's native `/api/chat` endpoint with JSON mode and a
generation cap of 1024 tokens (2048 for paper summaries). The per-run label
calls disable thinking (`think: false`) — reasoning traces are pure latency
for short JSON answers — while paper summaries keep thinking enabled via
`summary_params: {think: true}`: they run once per BioProject, so the
latency is worth the extraction quality. The server job runs with
`OLLAMA_CONTEXT_LENGTH=16384` (prompts are ≤8k tokens; the model's baked-in
262144 context would otherwise preallocate ~16x more KV memory) and
`OLLAMA_NUM_PARALLEL=32` so several label jobs can be served at once. The
server job requests all four H200s on the node; Ollama splits the model's
layers across them, which multiplies the KV budget and therefore the number
of concurrent requests the server can hold (per-token latency does not
improve). A 4-GPU job waits longer in the queue, so keep windows around
1,000 runs.

Tev1 requires Ollama 0.35 or newer. This workflow targets Ollama 0.40.11.

## RNA type filter

The workflow classifies the RNA species from SRA `library_strategy`,
`library_selection`, the library construction protocol, and selected
BioSample attributes. It does not use the paper, because a BioProject can mix
library types.

- `mrna` — polyA, poly(A), or oligo(dT) evidence.
- `ribo_depleted_total_rna` — RiboZero or rRNA-depleted total RNA.
- `total_rna` — total RNA without depletion.
- `small_rna` — miRNA, piRNA, siRNA, snoRNA, tRNA, or other small RNA.
- `lncrna`, `circrna`, `other_rna`, `not_rna`, `unknown`.

By default, `mrna` and `ribo_depleted_total_rna` continue to labeling. Change
`rna_type.accepted_rna_types` in `config/config.yaml` to alter that policy.
Excluded runs are written to `results/labels.excluded.tsv` with the RNA type,
source, evidence, and exclusion reason. Labeling rules short-circuit for
excluded runs, so they do not call Ollama or load the PECO index.

## Germplasm categories

The germplasm step mirrors the manual filtering in the paper: natural
accessions are retained, and modified lines are flagged for downstream
filtering. Every mRNA-eligible run stays in this step; `is_natural_accession`
is the filter column.

- `natural_accession`
- `mutant`
- `transgenic`
- `hybrid`
- `grafted`
- `cell_culture`
- `polyploid`
- `aneuploid`
- `unknown`

Rules first (SALK/SAIL/GABI/CS identifiers, 35S/GFP/GUS/RNAi/CRISPR markers,
etc.), then the Tev1 decision model, then the chat fallback.

## Two PECO layers

The workflow follows PECO's actual branches:

- **Plant exposure** (`PECO:0001001`): 511 terms including cold, high
  temperature, light, drought, control exposure, and growth-medium exposures.
  Retrieval selects candidates, and the chat model can return multiple terms.
- **Plant study condition** (`PECO:0007231`): four terms — greenhouse study,
  laboratory study, field study, growth chamber study — plus `OTHER`.

Because agar plates and hydroponics are PECO growth-medium **exposure** terms,
``results/labels.tsv`` also derives `growth_system_ids` / `growth_system_labels`
from exposure terms under `PECO:0007147`. That keeps those systems visible
without inventing a third PECO branch.

The exposure prompt uses the paper's annotation conventions: control is
long-day (≥12 h light, not constant), 18–26 °C, no stress or nutrient
limitation; high temperature is ≥27 °C; cold is ≤17 °C; short day is <12 h
light; recovery samples are labeled by the recovery condition. When a paper
reports them, `summarize_paper` also extracts `day_length_hours` and
`growth_temperature_c` (midpoint of a stated range); these flow into the
exposure prompt and `labels.tsv` as `paper_day_length_hours` /
`paper_growth_temperature_c`.

## PlantRNADB (ATHRDB) annotations

For Arabidopsis thaliana runs the workflow also fetches the human-curated
annotations from the [PlantRNADB Arabidopsis database](https://plantrnadb.com/athrdb/)
via the new `fetch_athrdb` rule (`results/metadata/athrdb/{run}.json`): curated
tissue, genotype, ecotype, project, release date, total reads, and mapped rate,
keyed by GEO GSM accession.

- Run → SRX lookup comes from the SRA metadata; SRX → GSM is resolved with an
  NCBI `db=gds` esearch/esummary pair. Runs without a GEO record get a
  `no_geo_record` stub.
- **Rate limiting**: ATHRDB queries run in a single serial Snakemake job, so
  the request rate never exceeds one request per
  `athrdb.min_interval_seconds` (default 2 s) regardless of how many jobs the
  workflow submits. Gaps get one-sided random jitter
  (`athrdb.jitter_fraction`, default 0.25) so the cadence is not a perfectly
  uniform interval; the gap never drops below the floor. A hard cap
  `athrdb.max_requests` (default 5000) leaves the
  remaining runs with `request_cap_reached` stubs; `athrdb.enabled: false`
  skips the site entirely. Skips are marked in `athrdb_note`, and reruns only
  query runs without an existing `results/metadata/athrdb/{run}.json`.
- ATHRDB is evidence, never blocking: failed lookups are recorded and the run
  proceeds. It is **not** an input to the tissue or germplasm labelers — the
  serial fetch would otherwise gate 40 chunk jobs per window. Instead,
  `aggregate` compares the curation against the model labels after labeling
  and adds the review reason `athrdb_disagreement` on a clash
  (`review.athrdb_crosscheck` in the config). `labels.tsv` carries
  `athrdb_gsm`, `athrdb_tissue`, `athrdb_genotype`, `athrdb_ecotype` for
  cross-checking during review.
- The review app shows the record (with a GEO link) in the "AthRDB" tab and
  reported day length / temperature on the paper card.

## ENA (ERR/SAMEA/PRJEB) submissions

Sheets with European (ENA) accessions work through NCBI's mirrors, with one
exception per record type:

| Record | ENA accession | Source |
|---|---|---|
| SRA experiment | `ERR…` / `ERX…` | NCBI `db=sra` mirrors ENA runs; no change |
| BioProject | `PRJEB…` | NCBI `db=bioproject` mirrors ENA studies; no change |
| BioSample | `SAMEA…` | **Often absent from NCBI.** Missing accessions fall back to ENA's BioSample XML API and are stored with `"fetch_source": "ena"`. Records from both sources share the same normalized shape. |
| ATHRDB curation | `SAMEA…` runs | GEO-keyed: ENA-only libraries get `no_geo_record` stubs and classify from SRA/BioSample evidence only. |

Accessions missing from both NCBI and ENA (typically typos) fail the window
loudly.

If a condition exists but no candidate fits, the exposure layer returns
`other: true` with a free-text `suggested_label` for review. `unknown`/`OTHER`
is also used for germplasm and study condition when the evidence is
insufficient.

## Tissue categories

The paper's categories, with flower and fruit separated:

`whole_plant`, `shoot`, `root`, `leaf`, `seed`, `flower`, `fruit`, plus `OTHER`.

The tissue rules layer reads **structured fields only** (`tissue`,
`organism part`, `plant structure`, …): Plant Ontology IDs from ENA
(`PO:0025034` → leaf, via `tissue.po_terms`) take precedence, then configured
keywords (including plurals such as `leaves` and the `rosette` → leaf
synonym). Free text in study titles/abstracts is model evidence only — keyword
hits there were the main source of wrong rule labels in the first window. The
germplasm rules layer has the same restriction (`germplasm.rule_attribute_keys`:
genotype, ecotype, cultivar, strain, library name, experiment title), which
prevents accession-shaped tokens in ENA submitter IDs from labeling transgenic
libraries as natural accessions.

## Output

`results/labels.tsv` contains only mRNA-eligible runs:

- `run`, `biosample`, `bioproject`, `species`
- `rna_type`, `rna_subtype`, `ribo_depleted`, `mrna_eligible`,
  `rna_type_source`, `rna_type_confidence`, `rna_type_evidence`
- `tissue`, `tissue_source`, `tissue_confidence`
- `germplasm_type`, `is_natural_accession`, `germplasm_confidence`,
  `germplasm_evidence`
- `peco_exposure_ids`, `peco_exposure_labels`, `peco_exposure_evidence`,
  `peco_exposure_other`, `peco_exposure_max_score`
- `peco_study_id`, `peco_study_label`, `peco_study_confidence`
- `growth_system_ids`, `growth_system_labels`
- `has_paper`, `paper_low_confidence`
- `review_required`, `review_reasons`

Review reasons: `rna_type_low_confidence`, `tissue_other`,
`tissue_low_confidence`, `germplasm_unknown`, `germplasm_low_confidence`,
`exposure_other`, `exposure_weak_retrieval`, `study_other`,
`study_low_confidence`, `athrdb_disagreement`, `mixed_run_context`. Paper availability is reported
in the `has_paper`/`paper_low_confidence` columns but does not itself trigger
review.

`results/labels.excluded.tsv` contains only non-eligible runs with `run`,
`biosample`, `bioproject`, `species`, `rna_type`, `rna_subtype`,
`ribo_depleted`, `rna_type_source`, `rna_type_confidence`, `rna_type_evidence`,
and `exclusion_reason`.

## Gene expression quantification

`rule quant_all` is a second target, not part of `rule all`: it quantifies every
mRNA-eligible run from `results/labels.tsv` and is far heavier than labeling.

```bash
# one-off: build the target list (the DAG shape depends on library layout)
python workflow/scripts/quant_prepare.py

# then run it
snakemake quant_all --profile workflow/profiles/default --resources quant_download=8
```

**Reads** come from ENA's `fastq_ftp` URLs when available (md5-verified,
resumable) and fall back to `prefetch` + `fasterq-dump --split-3` otherwise.
`fastp` trims each run — adapter auto-detection for paired-end, `--trim_poly_g`,
`-q 15 -u 40 -l 36` — and **never** runs `--dedup`: duplicate reads in RNA-seq
are usually biological, so only duplication *statistics* are collected.

**Salmon** quantifies per BioSample, not per run: the trimmed FASTQs of all runs
of a sample are passed as one library (`-1 a b -2 a b` / `-r a b`), so the TPM
column is directly comparable and needs no recomputation. The index is
decoy-aware with the whole genome as decoys (`salmon index -t gentrome -d
decoys.txt`), the documented best practice; `-l A` infers library type per
sample and is recorded in the QC table. Single-end libraries get Salmon's
documented defaults `--fldMean 250 --fldSD 25` (`quant.se_fld_mean` /
`quant.se_fld_sd`), because fragment length cannot be estimated from SE reads.

**Mixed layouts**: a BioSample whose runs differ in layout (157 of 9,209
multi-run samples in the current sheet) is quantified per run instead, and
counts are summed at merge time with TPM recomputed from gene lengths. Those
samples are marked `mode: per_run` in `results/quant/targets.tsv`.

**TIN** (transcript integrity number) is computed from Salmon's
`--writeMappings` BAM: per-transcript coverage gives `TIN = 100 ×
mean(cov)/max(cov)`, and the sample metric is the median across transcripts with
at least `quant.tin_min_coverage` reads. A 5′/3′ coverage skew is recorded
alongside it as a degradation indicator.

Outputs:

| File | Contents |
|---|---|
| `results/quant/gene_counts.tsv` | genes × BioSamples, Salmon `NumReads` |
| `results/quant/gene_tpm.tsv` | genes × BioSamples, TPM |
| `results/quant/quant_qc.tsv` | per sample: mode, layout, n_runs, mapped %, inferred library type, medTIN, per-run fastp QC |
| `results/quant/skipped.tsv` | runs excluded from quantification and why |

## Human review

The Streamlit app in `review_app/` groups runs by BioProject, shows the linked
paper and SRA/BioSample/BioProject metadata, and lets a reviewer edit tissue,
germplasm, exposure PECO terms, and study condition.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r review_app/requirements.txt
bash review_app/run.sh
```

Then open <http://127.0.0.1:8501>.

The app never edits `results/labels.tsv`. It stores human edits and review
status in `results/review/review.db`, and exports:

- `results/labels.reviewed.csv`
- `results/labels.reviewed.tsv`

A run counts as reviewed only after an explicit **Mark reviewed** action.
Reviewer names are self-declared. The SQLite database is designed for one
shared Streamlit process; use Postgres if you need multiple app hosts. See
[`review_app/README.md`](review_app/README.md) for details.

Export without the UI:

```bash
python -m review_app.export
```

## Requirements

- Snakemake 9.x and Conda/Mamba for the per-rule environments
- Ollama 0.40.11
- Models pulled: `qwen3.8` and `tev1:4b`

## Local run

```bash
export OLLAMA_SERVER="http://127.0.0.1:11434"
ollama serve &
snakemake -n
snakemake --sdm conda --cores 8
```

## Savio (H200)

One-time setup, from a login node:

```bash
# 1. Upgrade Ollama, keeping the known-good 0.34.4 binary as a rollback
cd /global/scratch/users/$USER/ollama
cp bin/ollama bin/ollama-0.34.4
curl -sL --fail -o ollama.tar.zst \
  https://github.com/ollama/ollama/releases/download/v0.40.11/ollama-linux-amd64.tar.zst
zstd -dc ollama.tar.zst | tar -xf -
rm ollama.tar.zst

# 2. Pull models (login node, not a GPU job)
export OLLAMA_MODELS=/global/scratch/users/$USER/ollama-models
export PATH=/global/scratch/users/$USER/ollama/bin:$PATH
ollama serve &
until curl -s http://127.0.0.1:11434 >/dev/null; do sleep 1; done
ollama pull qwen3.8
ollama pull tev1:4b
kill %1

# 3. Snakemake environment on scratch
mamba create -p /global/scratch/users/$USER/envs/sra-peco \
  -c conda-forge -c bioconda \
  snakemake=9.27.1 snakemake-executor-plugin-slurm=2.8.0 snakefmt=2.1.0
export PATH=/global/scratch/users/$USER/envs/sra-peco/bin:$PATH

# 4. Pre-create the rule environments on the login node
cd /global/home/users/$USER/moi_lab_projects/custom-rag-cli
snakemake --sdm conda \
  --conda-prefix /global/scratch/users/$USER/conda-envs/sra-peco \
  --conda-create-envs-only
```

Run the workflow:

```bash
cd /global/home/users/$USER/moi_lab_projects/custom-rag-cli
bash workflow/savio/run.sh
```

`run.sh` submits one four-H200 job that serves Ollama on `0.0.0.0:11434`,
waits for it to warm `qwen3.8`, checks that the login node can reach it, then
runs Snakemake with the default Slurm profile (`workflow/profiles/default`).
Rules run on `savio4_htc` and connect to the model server over the network.
`HF_HOME` and the conda prefix are redirected to scratch.

If compute-node networking is blocked, `run.sh` exits with a clear error. In
that case the fallback is per-rule GPU jobs, which reload the models per job.

## Validation

There is no automated gold set. Manual spot-check 30–50 stratified runs:

- 10 natural accessions, 10 mutants, 10 transgenics, 5 other non-natural
- 10 with a paper, 10 without
- 10 clear exposures, 10 ambiguous or control
- 10 study conditions stated, 10 unstated
- all seven tissue categories represented

Record expected values in a table with `run`, `expected_tissue`,
`expected_germplasm`, `natural_accession`, `expected_exposure_ids`,
`expected_study_id`, `expected_growth_system`, and `notes`. Track exact and
ancestor PECO agreement, set overlap for multiple exposures, tissue agreement,
and the false-natural rate. A mutant labeled `natural_accession` is the most
costly error.

Supplementary Table S5 from the paper is a useful optional cross-check, but it
is not part of the automated validation.

## Commit checks

Install the hooks once per clone:

```bash
pip install pre-commit
pre-commit install
```

The hooks run `snakefmt --check` and `scripts/lint-snakemake.sh` (the
`snakemake --lint` wrapper that drops the advisory-only "no log directive"
finding; the Slurm executor already persists job output in
`.snakemake/slurm_logs/`) on `workflow/` and `config/` changes, and
`ruff check` / `ruff format --check` on the Python sources. The `.github/workflows/sra-peco-ci.yml` workflow repeats these checks
on push and pull request, plus a `snakemake -n` dry run and the review-app
tests.

## RAG CLI

The original LlamaIndex RAG CLI remains in `src/`; see
[`src/README.md`](src/README.md) for its setup and Slurm usage.
