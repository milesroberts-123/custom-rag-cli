# custom-rag-cli

playing around with ollama and llama index to pass files to an LLM

## example usage on a slurm cluster

```bash
# submit interactive job with gpu
# ENSURE THAT YOU REQUEST THE CORRECT NUMBER OF CPUS PER GPU
srun --pty -A co_moilab -p savio4_gpu --qos savio_lowprio --gpus-per-task 1 --cpus-per-task 4 --ntasks 1 -t 01:00:00 bash -i

# activate ollama software and extra llama index needs
mamba activate /global/scratch/users/milesroberts/envs/ollama
module load anaconda3
module load ai/ollama/0.6.8

# run ollama server in background
ollama serve > /dev/null 2>&1 &

# Optionally download a LLM
# ollama pull tinyllama

# confirm model is now available
ollama list

# warm up a model
ollama run gemma3:1b What model are you? > response.txt

# model should match warmed up model above
# files should be a directory
./src/custom_rag_cli.py --model "gemma3:1b" --files papers --query "What are three main themes of these papers?"
```
