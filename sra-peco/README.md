# sra-peco

Snakemake workflow that labels SRA RNA-seq samples with plant tissue categories
and terms from the [Plant Experimental Conditions Ontology
(PECO)](https://www.ebi.ac.uk/ols4/ontologies/peco).

## Pipeline

1. Fetch BioSample records (attributes, organism) from NCBI.
2. Resolve each BioProject to a PubMed ID. Projects without a linked
   publication are skipped.
3. Fetch open-access full text (or the abstract) from Europe PMC.
4. Summarize the paper's experimental conditions once per BioProject.
5. Label each run's tissue category from BioSample metadata, using a rules
   pass, then the `tev1` decision model, then a chat fallback.
6. Retrieve candidate PECO terms and let a chat model select the ones that
   describe the sample's conditions.
7. Aggregate everything into `results/labels.tsv`.

## Inputs

`config/samples.tsv` — one SRA run per row:

```tsv
run	biosample	bioproject	species
SRR41450469	SAMN64520521	PRJNA1552792	Arabidopsis thaliana
```

`config/config.yaml` — workflow parameters. Replace `tissue.categories` and
`tissue.keywords` with your six tissue categories before running.

## Models

The default stack runs against one local Ollama server:

| Step | Model | Endpoint |
|---|---|---|
| Tissue | `tev1:4b` | `/v1/systemone` (decision) |
| Tissue fallback | `qwen3.8` | `/v1/chat/completions` |
| PECO | `qwen3.8` | `/v1/chat/completions` |
| Paper summary | `qwen3.8` | `/v1/chat/completions` |

`config/config.yaml` sets `ollama.server_url` and `ollama.api_key`. The
`OLLAMA_SERVER` and `OLLAMA_API_KEY` environment variables override them; the
Savio wrapper uses that to point at the model-server job.

Tev1's decision endpoint requires Ollama 0.35 or newer. This workflow targets
Ollama 0.40.11.

## Review flags

`results/labels.tsv` contains `review_required` and `review_reasons`. A row is
flagged when any of these hold:

- tissue is `OTHER` or the BioSample had no usable tissue attribute
- Tev1 confidence is below `review.tissue_confidence`
- PECO returned `other` (a condition exists but no candidate fits)
- the top PECO retrieval score is below `review.peco_retrieval_score`
- the project has no paper (`no_paper`)
- the paper summary is abstract-only or low confidence (`paper_low_confidence`)

`review_reasons` uses the codes `tissue_other`, `tissue_low_confidence`,
`peco_other`, `peco_weak_retrieval`, `no_paper`, and `paper_low_confidence`.

## Requirements

- Snakemake 9.x and Conda/Mamba for the per-rule environments
- Ollama 0.40.11 (for Tev1)
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
cd /global/home/users/$USER/moi_lab_projects/custom-rag-cli/sra-peco
snakemake --sdm conda \
  --conda-prefix /global/scratch/users/$USER/conda-envs/sra-peco \
  --conda-create-envs-only
```

Run the workflow:

```bash
cd /global/home/users/$USER/moi_lab_projects/custom-rag-cli/sra-peco
bash workflow/savio/run.sh
```

`run.sh` submits one H200 job that serves Ollama on `0.0.0.0:11434`, waits for
it to warm `qwen3.8`, checks that the login node can reach it, then runs
Snakemake with the `savio` profile. Rules run on `savio4_htc` and connect to the
model server over the network. `HF_HOME` and the conda prefix are redirected to
scratch.

If compute-node networking is blocked, `run.sh` exits with a clear error. In
that case the fallback is per-rule GPU jobs, which reload the models per job.

## Commit checks

Install the hooks once per clone:

```bash
pip install pre-commit
pre-commit install
```

The hooks run `snakefmt --check` and `snakemake --lint` on `sra-peco/` changes.
`.github/workflows/sra-peco-ci.yml` repeats both checks on push and pull
request, plus a `snakemake -n` dry run, scoped to `sra-peco/**`.
