# Configuration

The workflow reads two files from this directory:

- `config/config.yaml` — workflow parameters.
- `config/samples.tsv` — one SRA run per row.

All relative paths are resolved from the repository root. Override the sample
sheet without editing `config.yaml`:

```bash
snakemake -n --config samples=config/samples.test.tsv
```

## Sample sheet

`config/samples.tsv` must be tab-separated with these columns:

| Column | Description |
|---|---|
| `run` | SRA run accession (`SRR...`). Each run may appear once. |
| `biosample` | NCBI BioSample accession (`SAMN...`). |
| `bioproject` | NCBI BioProject accession (`PRJNA...`). |
| `species` | Scientific name, for example `Arabidopsis thaliana`. |

Example:

```tsv
run	biosample	bioproject	species
SRR41450469	SAMN64520521	PRJNA1552792	Arabidopsis thaliana
SRR41450470	SAMN64520520	PRJNA1552792	Arabidopsis thaliana
```

The workflow fetches BioSample and SRA metadata by accession. If a BioProject
has no linked PubMed ID, the paper stage is skipped for that project; the
sample is still labeled from metadata only.

## `samples`

Path to the sample sheet. Default: `config/samples.tsv`.

## `ncbi`

| Key | Default | Description |
|---|---|---|
| `email` | required | Contact email sent with NCBI E-utilities requests. |
| `api_key_env` | `NCBI_API_KEY` | Environment variable containing an NCBI API key. Optional, but raises the rate limit. |
| `batch_size` | `200` | BioSample accessions per efetch request. |
| `sra_batch_size` | `50` | SRA run accessions per efetch request. |
| `max_retries` | `5` | Retry attempts for NCBI requests. |

## `peco`

| Key | Default | Description |
|---|---|---|
| `url` | PECO OWL URL | Ontology download location. |
| `top_k` | `30` | Candidate terms passed to the exposure model. |
| `embed_model` | `BAAI/bge-base-en-v1.5` | Sentence-transformers model for retrieval. |
| `exposure_branch` | `PECO:0001001` | Root of the plant exposure branch. |
| `study_branch` | `PECO:0007231` | Root of the plant study condition branch. |
| `growth_system_root` | `PECO:0007147` | Root of growth-medium exposure terms used for `growth_system_*` columns. |
| `growth_system_extra_roots` | `[PECO:0007128, PECO:0007175]` | Additional exposure subtrees (photoperiod/day length, temperature regime) that also populate `growth_system_*`; the terms remain exposure annotations too. |

## `paper`

| Key | Default | Description |
|---|---|---|
| `max_chars` | `12000` | Maximum excerpt length sent to the paper-summary model. |

## `quant`

Gene-expression subworkflow (`snakemake quant_all`).

| Key | Default | Description |
|---|---|---|
| `paper.discover_by_accession` | `true` | Also search Europe PMC for the BioProject accession when NCBI has no linked publication. |
| `paper.max_pmids` | `3` | Candidate papers tried per project; the best text tier wins. |
| `paper.study_setting_map` | map | Maps a quoted paper setting to a PECO study-condition label. |
| `metadata.growth_keys` | list | Attribute keys counted as growth-condition evidence in `metadata_missing`. |
| `targets` | `results/quant/targets.tsv` | Target list produced by `python workflow/scripts/quant_prepare.py`. |
| `reference_release` | `60` | Ensembl Plants release recorded with the reference URLs. |
| `cdna_url` / `genome_url` / `gtf_url` | Ensembl Plants TAIR10 r60 | Reference FASTA and annotation; the GTF must match the cDNA release. |
| `salmon_k` | `31` | Salmon index k-mer size. |
| `trim_fastq_compress` | `false` | Write trimmed reads as `.fq.gz` instead of plain `.fq`. Thread counts are not set here; they live in `workflow/profiles/quant/config.yaml` (`set-threads`). |
| `se_fld_mean` | `250` | Assumed fragment length for single-end libraries (Salmon's documented default; SE reads cannot estimate it). |
| `se_fld_sd` | `25` | Assumed fragment-length SD for single-end libraries. |
| `tin_min_coverage` | `10` | Minimum reads per transcript before its TIN counts toward medTIN. |
| `scratch` | `/global/scratch/.../quant-tmp` | Temporary space for `fasterq-dump` and downloads. |

## `tissue`

| Key | Description |
|---|---|
| `categories` | Allowed tissue categories. |
| `keywords` | Keyword lists used by the rules fallback, keyed by category. |
| `attribute_keys` | BioSample attribute names searched by the rules fallback. |
| `other_description` | Description of the `OTHER` category sent to the model. |

## `germplasm`

| Key | Description |
|---|---|
| `categories` | Allowed germplasm categories. |
| `attribute_keys` | BioSample attribute names used as evidence. |
| `natural_accessions` | Accession names that count as natural accessions. |
| `patterns` | Regex lists keyed by germplasm category. |
| `descriptions` | Category descriptions sent to the decision model. |

The default categories are `natural_accession`, `mutant`, `transgenic`,
`hybrid`, `grafted`, `cell_culture`, `polyploid`, `aneuploid`, and `unknown`.

## `rna_type`

| Key | Description |
|---|---|
| `accepted_rna_types` | RNA types that continue to labeling. Defaults to `mrna` and `ribo_depleted_total_rna`. |
| `attribute_keys` | BioSample and SRA attribute names searched for RNA-type evidence. |
| `min_confidence` | Minimum model confidence for a fallback RNA-type call; lower values become `unknown`. |

The classifier uses SRA `library_strategy`, `library_selection`,
`library_source`, the library construction protocol, and selected BioSample or
SRA attributes. It does not use the paper. Other RNA types are written to
`results/labels.excluded.tsv`.

## `review`

| Key | Default | Description |
|---|---|---|
| `tissue_confidence` | `0.5` | Flag tissue calls below this confidence. |
| `germplasm_confidence` | `0.5` | Flag germplasm calls below this confidence. |
| `exposure_retrieval_score` | `0.55` | Flag exposure calls with a lower top retrieval score. |
| `study_confidence` | `0.5` | Flag study-condition calls below this confidence. |
| `rna_type_confidence` | `0.5` | Flag included RNA-type calls below this confidence. |
| `flag_missing_paper` | *(removed)* | Paper availability no longer triggers review; see `has_paper` column. |
| `athrdb_crosscheck` | `true` | Flag review when AthRDB curation disagrees with the tissue/germplasm labels. |

## `paper`

| Key | Default | Description |
|---|---|---|
| `max_chars` | `12000` | Character budget for the paper excerpt sent to the summary model. |

The paper summary also extracts `day_length_hours` and `growth_temperature_c`
when the paper reports them; `null` means not reported. These values are shown
in the review app and carried into `labels.tsv`.

## `athrdb`

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Query PlantRNADB for curated Arabidopsis annotations. |
| `base_url` | `https://plantrnadb.com/athrdb/Search.php` | Search endpoint. |
| `min_interval_seconds` | `2.0` | Minimum wall time between ATHRDB requests. The fetch is a single serial job, so this caps the request rate regardless of run count. |
| `jitter_fraction` | `0.25` | One-sided random jitter: each gap is `min_interval_seconds` plus up to this fraction of it, so the cadence is not a fixed metronome. `0` disables jitter. |
| `max_requests` | `5000` | Hard cap per fetch job; remaining runs get `request_cap_reached` stubs. `0` disables the cap. |
| `timeout` | `60` | Per-request HTTP timeout, seconds. |

Runs are queried once; reruns skip runs whose
`results/metadata/athrdb/{run}.json` already exists. Non-Arabidopsis runs are never
queried. Failed lookups are recorded in `athrdb_note` and never fail the
workflow.

## Window batching

Two optional top-level keys control batched invocations (also settable via
`--config batch_size=... batch_index=...`):

| Key | Default | Description |
|---|---|---|
| `batch_size` | `0` | Rows per window when batching a large sheet; `0` disables batching. |
| `batch_index` | `0` | One-based window to process; must be set together with `batch_size`. |
| `exposure_chunk_size` | `25` | Samples per exposure-labeling chunk (the slow layer; smaller chunks raise parallelism). |
| `label_chunk_size` | `50` | Runs per label chunk job; the four label rules load the interpreter/encoder once per chunk while outputs stay per-run. |

Windows slice the sheet in sheet order and are non-overlapping. The metadata
fetchers process only the window's accessions and skip files that already
exist, and `aggregate` rescans the full sheet, so `labels.tsv` accumulates all
completed runs across windows. See the README's "Batched runs" section for
the Savio run.sh recipe.

## `models`

| Key | Default | Description |
|---|---|---|
| `rna_type_backend` | `decision` | `decision`, `chat`, or `rules`. |
| `rna_type` | `qwen3.8` | Chat fallback model for RNA type. |
| `rna_type_decision` | `tev1:4b` | Tev1 decision model for RNA type. |
| `tissue_backend` | `decision` | `decision` uses `/v1/systemone`; `chat` uses the chat endpoint. |
| `tissue` | `qwen3.8` | Chat fallback model for tissue. |
| `tissue_decision` | `tev1:4b` | Tev1 decision model for tissue. |
| `germplasm_backend` | `decision` | Backend for germplasm. |
| `germplasm` | `qwen3.8` | Chat fallback model for germplasm. |
| `germplasm_decision` | `tev1:4b` | Tev1 decision model for germplasm. |
| `study_backend` | `decision` | Backend for study condition. |
| `study` | `qwen3.8` | Chat fallback model for study condition. |
| `study_decision` | `tev1:4b` | Tev1 decision model for study condition. |
| `exposure` | `qwen3.8` | Chat model for exposure labeling. |
| `summary` | `qwen3.8` | Chat model for paper summarization. |

Each `*_params` key is passed to the corresponding model request as Ollama
runtime options. The defaults set `temperature: 0` for deterministic calls.

Chat requests go to the native `/api/chat` endpoint with JSON mode and a
1024-token generation cap (2048 for paper summaries); single-choice chat
fallbacks and exposure share the default. Thinking is off by default and
opted into per step via a `think: true` entry in the step's `*_params` key
(it is sent as a top-level request field, not a runtime option): the
per-run label calls stay non-thinking for speed, while `summary_params`
sets `think: true` because summaries run once per BioProject and benefit
from the reasoning pass. Transient connection failures, timeouts, and HTTP
429/5xx are retried three times with backoff.

## `ollama`

| Key | Default | Description |
|---|---|---|
| `server_url` | `http://127.0.0.1:11434` | Ollama server used by the rule scripts. |
| `api_key` | `ollama` | Placeholder key for the OpenAI-compatible client. |

Environment variables override these values:

- `OLLAMA_SERVER` overrides `ollama.server_url`.
- `OLLAMA_API_KEY` overrides `ollama.api_key`.
- `NCBI_API_KEY` is read according to `ncbi.api_key_env`.

## Running

```bash
# Parse the workflow and check the DAG.
snakemake -n

# Run with Conda-deployed rule environments.
snakemake --sdm conda --cores 8
```

On Savio, `workflow/savio/run.sh` starts a shared Ollama server on an H200 and
runs the CPU rules with the Slurm profile. See the repository README for the
one-time setup.
