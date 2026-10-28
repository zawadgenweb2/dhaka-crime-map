#!/usr/bin/env bash
# EmbeddingGemma 2 for the cross-paper matcher (app/events.py): loopback only, ~0.6 GB of GPU memory.
set -euo pipefail
RT="$HOME/.local/opt/dhaka-llama-b11669-cu122"
MODEL="$HOME/.local/share/dhaka-llm/${DHAKA_EMBED_MODEL:-embeddinggemma-2-Q8_0.gguf}"
exec env LD_LIBRARY_PATH="$RT/lib" CUDA_VISIBLE_DEVICES=0 "$RT/bin/llama-server" \
  --model "$MODEL" --alias dhaka-embed \
  --host 127.0.0.1 --port 8091 \
  --embedding --pooling mean \
  --n-gpu-layers 999 --ctx-size 8192 --batch-size 2048 --ubatch-size 2048 --parallel 2 --no-webui
