#!/bin/bash
# Run the workflow on Savio: one H200 job serves Ollama, CPU jobs run the rules.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p .snakemake/slurm_logs resources

export PATH="/global/scratch/users/$USER/envs/sra-peco/bin:$PATH"
export HF_HOME="${HF_HOME:-/global/scratch/users/$USER/hf-cache}"
mkdir -p "$HF_HOME"

SERVER_FILE="$ROOT/resources/ollama_server.txt"
rm -f "$SERVER_FILE"

JOB_ID="$(sbatch --parsable workflow/savio/ollama-server.sbatch "$SERVER_FILE")"
JOB_ID="${JOB_ID%%;*}"
echo "Submitted the Ollama server as Slurm job $JOB_ID"

for _ in $(seq 1 1800); do
    [[ -f "$SERVER_FILE" ]] && break
    sleep 2
done

if [[ ! -f "$SERVER_FILE" ]]; then
    echo "The Ollama server did not become ready within an hour." >&2
    echo "Inspect .snakemake/slurm_logs/ollama-${JOB_ID}.out" >&2
    scancel "$JOB_ID" || true
    exit 1
fi

HOST="$(cat "$SERVER_FILE")"
export OLLAMA_SERVER="http://$HOST"
export OLLAMA_API_KEY="ollama"

cleanup() {
    scancel "$JOB_ID" || true
    rm -f "$SERVER_FILE"
}
trap cleanup EXIT

echo "Checking $OLLAMA_SERVER from $(hostname)"
if ! curl -sf "$OLLAMA_SERVER/api/tags" >/dev/null; then
    echo "Cannot reach $OLLAMA_SERVER from this node." >&2
    echo "Compute-node networking may be blocked; use per-rule GPU jobs instead." >&2
    exit 1
fi

# run snakemake with any extra arguments passed through
snakemake --sdm conda --no-temp "$@"
