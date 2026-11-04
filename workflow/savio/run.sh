#!/bin/bash
# Run the workflow on Savio: one H200 job serves Ollama, CPU jobs run the rules.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p .snakemake/slurm_logs results resources

export PATH="/global/scratch/users/$USER/envs/sra-peco/bin:$PATH"
export HF_HOME="${HF_HOME:-/global/scratch/users/$USER/hf-cache}"
mkdir -p "$HF_HOME"

SERVER_FILE="$ROOT/results/ollama_server.txt"
rm -f "$SERVER_FILE"

JOB_ID="$(sbatch --parsable workflow/savio/ollama-server.sbatch "$SERVER_FILE")"
JOB_ID="${JOB_ID%%;*}"
echo "Submitted the Ollama server as Slurm job $JOB_ID"

# Wait for the server file. The job may sit in the GPU queue for a long time
# and the model warm-up takes minutes on scratch I/O, so keep waiting while
# the job is still alive (up to a generous cap). Fail immediately if the job
# leaves the queue without producing the file.
CAP=$((4 * 60 * 60 / 10)) # 4 hours at 10 s polls
for _ in $(seq 1 "$CAP"); do
    [[ -f "$SERVER_FILE" ]] && break
    STATE="$(squeue -h -j "$JOB_ID" -o %T 2>/dev/null || true)"
    if [[ -z "$STATE" ]]; then
        echo "Ollama server job $JOB_ID left the queue without becoming ready." >&2
        echo "Job log tail (.snakemake/slurm_logs/ollama-${JOB_ID}.out):" >&2
        tail -20 ".snakemake/slurm_logs/ollama-${JOB_ID}.out" >&2 || true
        echo "Error log tail (.snakemake/slurm_logs/ollama-${JOB_ID}.err):" >&2
        tail -5 ".snakemake/slurm_logs/ollama-${JOB_ID}.err" >&2 || true
        exit 1
    fi
    sleep 10
done

if [[ ! -f "$SERVER_FILE" ]]; then
    echo "The Ollama server did not become ready within 4 hours." >&2
    echo "The job $JOB_ID is still queued or warming up; inspect" >&2
    echo ".snakemake/slurm_logs/ollama-${JOB_ID}.out" >&2
    echo "(a common cause: qwen3.8 served on CPU, not GPU - see that log)" >&2
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
