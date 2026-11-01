#!/bin/bash
#SBATCH --job-name=sra-peco-ollama
#SBATCH -A co_moilab
#SBATCH -p savio4_gpu
#SBATCH --qos moilab_gpu4_normal
#SBATCH --gres=gpu:H200:1
#SBATCH --cpus-per-gpu 32
#SBATCH --time=12:00:00
#SBATCH --output=logs/slurm/ollama-%j.out
#SBATCH --error=logs/slurm/ollama-%j.err

set -euo pipefail

export OLLAMA_MODELS=/global/scratch/users/$USER/ollama-models
export PATH=/global/scratch/users/$USER/ollama/bin:$PATH
export OLLAMA_LLM_LIBRARY=vulkan
export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_KEEP_ALIVE=2h
export OLLAMA_MAX_LOADED_MODELS=2

SERVER_FILE="${1:?usage: ollama-server.sbatch <server-file>}"
mkdir -p "$(dirname "$SERVER_FILE")" logs

cleanup() {
    rm -f "$SERVER_FILE"
    pkill -u "$USER" -x ollama || true
}
trap cleanup EXIT

if ! pgrep -u "$USER" -x ollama >/dev/null; then
    ollama serve > "logs/ollama-serve-${SLURM_JOB_ID}.log" 2>&1 &
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

echo "Ollama is serving on $(hostname):11434"
ollama ps
echo "$(hostname):11434" > "$SERVER_FILE"

wait
