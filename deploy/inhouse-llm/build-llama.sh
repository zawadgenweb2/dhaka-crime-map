#!/usr/bin/env bash
# Build llama.cpp b11669 (v0.7.0) for CUDA 12.2 / sm_86 in a throwaway container; install to ~/.local/opt.
set -euo pipefail
umask 077
RT="$HOME/.local/opt/dhaka-llama-b11669-cu122"
if [ -x "$RT/bin/llama-server" ]; then echo "already built"; exit 0; fi
mkdir -p "$RT"
docker run --rm --cpus=8 --memory=12g --pids-limit=1024 \
  -e TASK_UID="$(id -u)" -e TASK_GID="$(id -g)" \
  --mount "type=bind,src=$RT,dst=/out" \
  nvidia/cuda:12.2.2-devel-ubuntu20.04@sha256:1014b3265691259e8df40b6326abebc5adecee17e372404569dee837ac9cec08 \
  bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends build-essential ca-certificates curl python3 python3-pip >/dev/null
    python3 -m pip install -q --no-cache-dir cmake==3.31.6
    curl -sS --fail --location \
      https://codeload.github.com/ggml-org/llama.cpp/legacy.tar.gz/620d2225cc436ab0b001e3200e590e3b286ef9ab \
      --output /tmp/llama.tar.gz
    printf "%s  %s\n" da36b3375b80d9d237e3787ff04fa72887bce2c8eefb717023205e4e6bbdeaad /tmp/llama.tar.gz | sha256sum --check -
    mkdir /tmp/llama && tar -xzf /tmp/llama.tar.gz --strip-components=1 -C /tmp/llama
    cmake -S /tmp/llama -B /tmp/llama/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF \
      -DGGML_OPENMP=OFF -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86-real -DGGML_CUDA_GRAPHS=OFF -DGGML_CUDA_NO_VMM=ON \
      -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_APP=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_UI=OFF \
      -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_NUMBER=11669 -DLLAMA_BUILD_COMMIT=620d222 >/dev/null
    cmake --build /tmp/llama/build --target llama-server -j8 2>&1 | tail -3
    install -Dm755 /tmp/llama/build/bin/llama-server /out/bin/llama-server
    mkdir -p /out/lib
    for l in libcudart.so.12 libcublas.so.12 libcublasLt.so.12; do cp -L "/usr/local/cuda/lib64/$l" /out/lib/; done
    cp -L /usr/lib/x86_64-linux-gnu/libstdc++.so.6 /usr/lib/x86_64-linux-gnu/libgcc_s.so.1 /out/lib/
    chown -R "$TASK_UID:$TASK_GID" /out
  '
LD_LIBRARY_PATH="$RT/lib" "$RT/bin/llama-server" --version
echo BUILD_OK
