# custom-rag-cli

Annotate biosamples from RNA-seq experiments with tissue type, PECO ontology treatment conditions, and study type using scientific paper PDFs and a local LLM (Ollama + LlamaIndex).

## How it works

For each biosample in the metadata file, the script:

1. Retrieves relevant context from the provided PDFs using RAG (vector similarity search)
2. Sends the biosample metadata, relevant paper excerpts, and the full PECO ontology term list to a local Ollama LLM
3. Parses the LLM's structured response (tissue type, PECO terms, study type)
4. Writes all results to a tab-separated values (TSV) file

## Input files

### 1. PDFs of scientific papers (`--pdfs`)

A directory containing `.pdf` files of the papers relevant to the biosamples. Papers are indexed once at startup into a vector store; relevant chunks are retrieved per biosample.

### 2. Biosample metadata (`--metadata`)

Tabular metadata with biosample attributes. The parser expects the NCBI-style format used in `test/biosample_result.txt`:

```
1: Cat-0 (9832)
Identifiers: BioSample: SAMN04910990; SRA: SRS1416138; GEO: GSM2136304
Organism: Arabidopsis thaliana
Attributes:
    /source name="rosette leaves"
    /cultivar="Cat-0"
    /ecotype id="9832"
    /development stage="before bolting"
    /light condition="long day"
    /tissue="leaf"
Accession: SAMN04910990    ID: 4910990
```

Attribute names are not standardized — the parser extracts all `/key="value"` lines.

### 3. PECO ontology terms (`--peco`)

A CSV export of the Plant Experimental Conditions Ontology (PECO), formatted like `test/PECO.csv`. The parser extracts each term's ID, preferred label, and definition.

## Output

A TSV file with these columns:

| Column | Description |
|---|---|
| `BioSample` | Biosample accession ID |
| `tissue type` | One of: leaf, root, shoot, fruit, flower, seed, whole plant |
| `treatment conditions` | PECO term(s) in `ID: label; ID: label` format |
| `study type` | One of: laboratory, growth chamber, greenhouse, outdoor/field |

## CLI parameters

```
Usage: custom_rag_cli.py [OPTIONS]

Options:
  --instructions TEXT      Custom natural-language instructions for mapping
                           labels onto biosamples (any text).
  --pdfs PATH              Path to folder containing PDF scientific papers.
                           [required]
  --metadata PATH          Path to biosample metadata file.  [required]
  --peco PATH              Path to PECO ontology terms CSV file.  [required]
  --model TEXT             Ollama model name.  [default: gemma3:1b]
  --temperature FLOAT      LLM temperature (0 = deterministic).  [default: 0.0]
  --context-window INTEGER Context window size in tokens.  [default: 4096]
  --topk INTEGER           Number of similar document chunks to retrieve per
                           query.  [default: 5]
  --output PATH            Output TSV file path.
                           [default: biosample_annotations.tsv]
  --start INTEGER          0-based start index in biosample list (for resuming
                           interrupted runs).  [default: 0]
  --limit INTEGER          Maximum number of biosamples to process (0 = all).
                           [default: 0]
  --help                   Show this message and exit.
```

## Example usage on a Slurm cluster

```bash
# submit interactive job with GPU
# ensure you request the correct number of CPUs per GPU
srun --pty -A co_moilab -p savio4_gpu --qos savio_lowprio \
     --gpus-per-task 1 --cpus-per-task 4 --ntasks 1 -t 02:00:00 bash -i

# activate ollama software and llama-index dependencies
mamba activate /global/scratch/users/milesroberts/envs/ollama
module load anaconda3
module load ai/ollama/0.6.8

# start ollama server in background
ollama serve > /dev/null 2>&1 &

# confirm model is available and warm it up
ollama run gemma3:1b "What model are you?" > /dev/null

# run annotation
./src/custom_rag_cli.py \
    --instructions "These are Arabidopsis ecotypes grown under standard long-day conditions." \
    --pdfs papers/ \
    --metadata test/biosample_result.txt \
    --peco test/PECO.csv \
    --model gemma3:1b \
    --temperature 0.0 \
    --context-window 4096 \
    --topk 5 \
    --output annotations.tsv

# process a subset (indices 0–9, useful for testing)
./src/custom_rag_cli.py \
    --pdfs papers/ \
    --metadata test/biosample_result.txt \
    --peco test/PECO.csv \
    --limit 10
```

## Resuming interrupted runs

Use `--start` and `--limit` to process biosamples in batches:

```bash
# first 100
./src/custom_rag_cli.py ... --start 0 --limit 100 --output batch1.tsv

# next 100
./src/custom_rag_cli.py ... --start 100 --limit 100 --output batch2.tsv
```

Append results together afterward:

```bash
head -1 batch1.tsv > all.tsv
tail -n +2 batch1.tsv >> all.tsv
tail -n +2 batch2.tsv >> all.tsv
```

## Custom instructions

Use `--instructions` to provide domain-specific guidance to the LLM, e.g.:

```bash
--instructions "All samples come from a drought stress experiment conducted in a greenhouse. Prefer drought-related PECO terms."
```
