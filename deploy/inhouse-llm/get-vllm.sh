#!/usr/bin/env bash
# Optional faster runtime: vLLM 0.32.0 in a user-space venv (no sudo, no Docker GPU access needed).
# Stops early if PyTorch's CUDA 12.9 build cannot use the GPU with this host's driver.
set -euo pipefail
UV="$HOME/.local/bin/uv"
VENV="$HOME/.local/opt/dhaka-vllm-0.32.0"
MODELS="$HOME/.local/share/dhaka-llm/hf"
[ -x "$UV" ] || { echo "uv missing at $UV"; exit 1; }
[ -x "$VENV/bin/python" ] || "$UV" venv -q --python 3.12 "$VENV"
"$UV" pip install -q --python "$VENV/bin/python" "vllm==0.32.0" --torch-backend=cu129
"$VENV/bin/python" - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
assert torch.cuda.is_available(), "PyTorch cannot use the GPU with this driver"
x = torch.randn(2048, 2048, device="cuda", dtype=torch.bfloat16)
print("matmul ok", float((x @ x).float().abs().mean()) > 0, torch.cuda.get_device_name(0))
PY
"$VENV/bin/vllm" download-kernels || echo "download-kernels failed (continuing; kernels may JIT)"
mkdir -p "$MODELS"
"$VENV/bin/hf" download google/gemma-4-E2B-it --local-dir "$MODELS/gemma-4-E2B-it" \
  --include "*.json" "*.safetensors" "tokenizer*" "*.jinja"
echo VLLM_READY
