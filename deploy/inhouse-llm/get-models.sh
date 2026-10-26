#!/usr/bin/env bash
# Download pinned, checksum-verified GGUF models.
set -euo pipefail
M="$HOME/.local/share/dhaka-llm"; mkdir -p "$M" "$HOME/.config/dhaka-llm"
fetch() { # repo revision file sha256
  local out="$M/$3"
  if [ -f "$out" ]; then echo "have $3"; return; fi
  curl -sS --fail --location "https://huggingface.co/$1/resolve/$2/$3" --output "$out.part"
  printf '%s  %s\n' "$4" "$out.part" | sha256sum --check -
  mv "$out.part" "$out"; echo "got $3"
}
fetch ggml-org/gemma-4-E2B-it-GGUF 6938c58e698502037401a5f19f6905f2fb2f7dee gemma-4-E2B-it-Q8_0.gguf \
  996d08777aadc6bfd3c7375ef70ba25a0f55240075860754fdb18d6d860aa63a
[ -f "$HOME/.config/dhaka-llm/api-key" ] || { openssl rand -hex 32 > "$HOME/.config/dhaka-llm/api-key"; chmod 600 "$HOME/.config/dhaka-llm/api-key"; }
echo MODELS_OK
