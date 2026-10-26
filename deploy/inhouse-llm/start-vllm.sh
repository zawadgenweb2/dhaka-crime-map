#!/usr/bin/env bash
# vLLM alternative to start-llama.sh: same port, API key and model alias, so the classifier needs no change.
set -euo pipefail
VENV="$HOME/.local/opt/dhaka-vllm-0.32.0"
MODEL="$HOME/.local/share/dhaka-llm/hf/${DHAKA_VLLM_MODEL:-gemma-4-E2B-it}"
export VLLM_API_KEY="$(cat "$HOME/.config/dhaka-llm/api-key")"   # env, not argv: keeps the key out of `ps`
exec "$VENV/bin/vllm" serve "$MODEL" --served-model-name dhaka-gemma \
  --host 127.0.0.1 --port 8090 \
  --quantization "${DHAKA_VLLM_QUANT:-fp8}" \
  --max-model-len "${DHAKA_LLM_CTX:-16384}" --gpu-memory-utilization 0.88 \
  --enable-prefix-caching --max-num-seqs 4 \
  --limit-mm-per-prompt '{"image": 0, "audio": 0, "video": 0}' \
  --generation-config vllm
