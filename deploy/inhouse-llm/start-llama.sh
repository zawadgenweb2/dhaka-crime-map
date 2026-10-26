#!/usr/bin/env bash
# Start llama-server for the classifier: GPU, loopback only, API key, one slot, model kept loaded.
# MODEL defaults to Gemma 4 E2B Q8; override with DHAKA_LLM_MODEL=<file in ~/.local/share/dhaka-llm>.
set -euo pipefail
RT="$HOME/.local/opt/dhaka-llama-b11669-cu122"
MODEL="$HOME/.local/share/dhaka-llm/${DHAKA_LLM_MODEL:-gemma-4-E2B-it-Q8_0.gguf}"
exec env LD_LIBRARY_PATH="$RT/lib" CUDA_VISIBLE_DEVICES=0 "$RT/bin/llama-server" \
  --model "$MODEL" --alias dhaka-gemma \
  --host 127.0.0.1 --port 8090 \
  --api-key-file "$HOME/.config/dhaka-llm/api-key" \
  --parallel 1 --ctx-size "${DHAKA_LLM_CTX:-16384}" \
  --n-gpu-layers 999 --threads 4 --threads-batch 8 \
  --n-predict 4096 --cache-prompt --no-context-shift --no-webui
