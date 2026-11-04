#!/bin/bash
#SBATCH --job-name=sra-peco-ollama
#SBATCH -A co_moilab
#SBATCH -p savio4_gpu
#SBATCH --qos moilab_gpu4_normal
#SBATCH --gres=gpu:H200:1
#SBATCH --cpus-per-gpu 32
#SBATCH --time=12:00:00
#SBATCH --output=.snakemake/slurm_logs/ollama-%j.out
#SBATCH --error=.snakemake/slurm_logs/ollama-%j.err

set -euo pipefail

export OLLAMA_MODELS=/global/scratch/users/$USER/ollama-models
export PATH=/global/scratch/users/$USER/ollama/bin:$PATH
export OLLAMA_LLM_LIBRARY=vulkan
export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_KEEP_ALIVE=2h
export OLLAMA_MAX_LOADED_MODELS=2
# Prompts never exceed ~8k tokens, so shrink the context from the model's
# baked-in 262144. This cuts the KV cache preallocation ~16x (memory and
# prefill cost) and makes room for more parallel slots. Requests are capped
# with num_predict on the client side.
export OLLAMA_CONTEXT_LENGTH=16384
export OLLAMA_NUM_PARALLEL=8

SERVER_FILE="${1:?usage: ollama-server.sbatch <server-file>}"
mkdir -p "$(dirname "$SERVER_FILE")" .snakemake/slurm_logs

cleanup() {
    rm -f "$SERVER_FILE"
    pkill -u "$USER" -x ollama || true
}
trap cleanup EXIT

# Start a server only if nothing is already listening on this node. Each GPU
# job gets the whole node, so any existing listener here would be ours or a
# leftover from a crashed job; probing the port avoids reusing a stale
# CPU-only server from a login node.
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ollama serve > ".snakemake/slurm_logs/ollama-serve-${SLURM_JOB_ID}.log" 2>&1 &
fi

until curl -sf http://127.0.0.1:11434/api/tags >/dev/null; do
    sleep 1
done

if ! ollama list | grep -q '^qwen3.8'; then
    echo "qwen3.8 is not pulled; run 'ollama pull qwen3.8' on a login node" >&2
    exit 1
fi

# Warm the generation model so the first real request is not a cold load.
ollama run qwen3.8 "Reply with OK" >/dev/null

# The generation model must be served from the GPU. If Vulkan discovery broke
# (a known risk with the Ollama 0.40.11 upgrade), ollama silently falls back
# to CPU and every label job times out. Fail loudly instead of wasting hours.
if ! ollama ps | grep -E '^qwen3\.8' | grep -q 'GPU'; then
    echo "qwen3.8 is loaded on CPU, not GPU:" >&2
    ollama ps >&2
    echo "Remediation: restore the known-good 0.34.4 ollama binary and" >&2
    echo "re-run; or debug Vulkan discovery with 'ollama ps' after restarting" >&2
    echo "the server manually (OLLAMA_LLM_LIBRARY=vulkan)." >&2
    exit 1
fi

echo "Ollama is serving on $(hostname):11434"
ollama ps
echo "$(hostname):11434" > "$SERVER_FILE"

wait