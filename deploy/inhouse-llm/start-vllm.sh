#!/usr/bin/env bash
# vLLM alternative to start-llama.sh: same port, API key and model alias, so the classifier needs no change
# except GEMMA_JSON_WHITESPACE=bounded (see below).
#
# Tuned on the RTX 3080 Ti (12 GB, sm_86) with vLLM 0.32.0+cu129 and Google's QAT w4a16 checkpoints
# (compressed-tensors, Marlin kernels). Benchmark notes: docs/ENGINEERING.md §9.
#   - Pre-quantized checkpoint: no --quantization flag (DHAKA_VLLM_QUANT empty); set it only for bf16 checkpoints.
#   - torch.compile is off (mode 0): its autotuning needs ~5 GB extra and runs out of memory on 12 GB.
#     CUDA graphs for decode are kept (FULL_DECODE_ONLY): without them decode drops from ~120 to ~15 tokens/s.
#   - JSON via the llguidance backend: the classifier caps whitespace in the schema (x-guidance); xgrammar's
#     unbounded whitespace let the model loop on newlines, and its no-whitespace mode broke the answers.
#   - FlashInfer sampler off: it JIT-compiles with nvcc+ninja, which this host does not have; temperature 0 anyway.
set -euo pipefail
VENV="$HOME/.local/opt/dhaka-vllm-0.32.0"
MODEL="$HOME/.local/share/dhaka-llm/hf/${DHAKA_VLLM_MODEL:-gemma-4-E2B-it-qat-w4a16-ct}"
QUANT="${DHAKA_VLLM_QUANT-}"
export VLLM_API_KEY="$(cat "$HOME/.config/dhaka-llm/api-key")"   # env, not argv: keeps the key out of `ps`
export VLLM_USE_FLASHINFER_SAMPLER=0
exec "$VENV/bin/vllm" serve "$MODEL" --served-model-name dhaka-gemma \
  --host 127.0.0.1 --port 8090 \
  ${QUANT:+--quantization "$QUANT"} \
  --max-model-len "${DHAKA_LLM_CTX:-8192}" --gpu-memory-utilization "${DHAKA_VLLM_GPU_UTIL:-0.90}" \
  --max-num-seqs "${DHAKA_VLLM_SEQS:-2}" --max-num-batched-tokens 2048 \
  --enable-prefix-caching \
  --structured-outputs-config '{"backend": "guidance"}' \
  -cc '{"mode": 0, "cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1, 2]}' \
  --limit-mm-per-prompt '{"image": 0, "audio": 0, "video": 0}' \
  --generation-config vllm
