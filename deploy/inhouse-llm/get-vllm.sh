#!/usr/bin/env bash
# Optional faster runtime: vLLM 0.32.0 in a user-space venv (no sudo, no Docker GPU access needed).
# Stops early if PyTorch's CUDA 12.9 build cannot use the GPU with this host's driver.
set -euo pipefail
UV="$HOME/.local/bin/uv"
VENV="$HOME/.local/opt/dhaka-vllm-0.32.0"
MODELS="$HOME/.local/share/dhaka-llm/hf"
[ -x "$UV" ] || { echo "uv missing at $UV"; exit 1; }
[ -x "$VENV/bin/python" ] || "$UV" venv -q --python 3.12 "$VENV"
# The default PyPI wheel of vllm 0.32.0 is built against CUDA 13 (needs driver >= 580, unavailable on
# Ubuntu 20.04). Use the release's CUDA 12.9 wheel instead; driver 575.57 supports CUDA 12.9 natively.
W="vllm-0.32.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl"
[ -f "$HOME/dhaka-llm/$W" ] || curl -sSfL -o "$HOME/dhaka-llm/$W" \
  "https://github.com/vllm-project/vllm/releases/download/v0.32.0/vllm-0.32.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl"
echo "9918be806fb2808c406547ff4f9f43870ac6ff28dc4b179291fcf532145bb50b  $HOME/dhaka-llm/$W" | sha256sum -c -
"$UV" pip install -q --python "$VENV/bin/python" "$HOME/dhaka-llm/$W" --torch-backend=cu129
"$VENV/bin/python" - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
assert torch.cuda.is_available(), "PyTorch cannot use the GPU with this driver"
x = torch.randn(2048, 2048, device="cuda", dtype=torch.bfloat16)
print("matmul ok", float((x @ x).float().abs().mean()) > 0, torch.cuda.get_device_name(0))
PY
"$VENV/bin/python" -c "import vllm._C_stable_libtorch, vllm.platforms as p; assert p.current_platform.device_name == 'cuda'"
"$VENV/bin/vllm" download-kernels || echo "download-kernels failed (continuing; kernels may JIT)"
mkdir -p "$MODELS"
# Pinned revision; on a slow link, fetch on a faster machine and copy (see dcm fetch notes in README).
"$VENV/bin/hf" download google/gemma-4-E2B-it --revision 3e22461f65e89153144f8adb70e3b8c2cc9845a7 \
  --local-dir "$MODELS/gemma-4-E2B-it" --include "*.json" "*.safetensors" "*.jinja"
echo VLLM_READY
