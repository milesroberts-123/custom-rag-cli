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
| `logs/` | Snakemake and Slurm logs |

## Pipeline

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

## Models

The default stack runs against one local Ollama server:

| Step | Model | Endpoint |
|---|---|---|
| RNA type | `tev1:4b` | `/v1/systemone` (decision) |
| Tissue | `tev1:4b` | `/v1/systemone` (decision) |
| Germplasm | `tev1:4b` | `/v1/systemone` (decision) |
| Study condition | `tev1:4b` | `/v1/systemone` (decision) |
| Exposure | `qwen3.8` | `/v1/chat/completions` |
| Paper summary | `qwen3.8` | `/v1/chat/completions` |

Each decision step falls back to the chat model if the decision endpoint
fails. `config/config.yaml` sets `ollama.server_url` and `ollama.api_key`; the
`OLLAMA_SERVER` and `OLLAMA_API_KEY` environment variables override them.

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
  proceeds. Its tissue/genotype/ecotype lines are appended to the tissue and
  germplasm prompts, and `labels.tsv` carries `athrdb_gsm`, `athrdb_tissue`,
  `athrdb_genotype`, `athrdb_ecotype` for cross-checking during review.
- The review app shows the record (with a GEO link) in the "AthRDB" tab and
  reported day length / temperature on the paper card.

If a condition exists but no candidate fits, the exposure layer returns
`other: true` with a free-text `suggested_label` for review. `unknown`/`OTHER`
is also used for germplasm and study condition when the evidence is
insufficient.

## Tissue categories

The paper's categories, with flower and fruit separated:

`whole_plant`, `shoot`, `root`, `leaf`, `seed`, `flower`, `fruit`, plus `OTHER`.

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
`study_low_confidence`, `no_paper`, `paper_low_confidence`.

`results/labels.excluded.tsv` contains only non-eligible runs with `run`,
`biosample`, `bioproject`, `species`, `rna_type`, `rna_subtype`,
`ribo_depleted`, `rna_type_source`, `rna_type_confidence`, `rna_type_evidence`,
and `exclusion_reason`.

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

`run.sh` submits one H200 job that serves Ollama on `0.0.0.0:11434`, waits for
it to warm `qwen3.8`, checks that the login node can reach it, then runs
Snakemake with the default Slurm profile (`workflow/profiles/default`). Rules
run on `savio4_htc` and connect to the model server over the network. `HF_HOME`
and the conda prefix are redirected to scratch.

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

The hooks run `snakefmt --check` and `snakemake --lint` on `workflow/` and
`config/` changes, and `ruff check` / `ruff format --check` on the Python
sources. The `.github/workflows/sra-peco-ci.yml` workflow repeats these checks
on push and pull request, plus a `snakemake -n` dry run and the review-app
tests.

## RAG CLI

The original LlamaIndex RAG CLI remains in `src/`; see
[`src/README.md`](src/README.md) for its setup and Slurm usage.
