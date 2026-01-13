#!/bin/bash
# serve_model.sh - Launch vLLM OpenAI-compatible server for Qwen model
#
# This script is designed to run on RunPod or similar GPU instances.
# Requirements:
#   - NVIDIA GPU with at least 16GB VRAM (24GB recommended)
#   - Python 3.10+
#   - vLLM installed: pip install vllm
#
# Usage:
#   chmod +x serve_model.sh
#   ./serve_model.sh
#
# Or with custom settings:
#   VLLM_PORT=8000 VLLM_GPU_UTIL=0.90 ./serve_model.sh

set -e

# Configuration (override with environment variables)
MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
SERVED_NAME="${VLLM_SERVED_NAME:-qwen2.5-7b}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_UTIL:-0.90}"
MAX_MODEL_LEN="${VLLM_MAX_LEN:-32768}"
DTYPE="${VLLM_DTYPE:-auto}"
API_KEY="${VLLM_API_KEY:-token-anything}"

echo "=============================================="
echo "Starting vLLM OpenAI Server"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Served Name: ${SERVED_NAME}"
echo "Host: ${HOST}:${PORT}"
echo "GPU Memory Utilization: ${GPU_MEMORY_UTILIZATION}"
echo "Max Model Length: ${MAX_MODEL_LEN}"
echo "=============================================="

# Check for GPU
if ! nvidia-smi > /dev/null 2>&1; then
    echo "ERROR: nvidia-smi not found. GPU required."
    exit 1
fi

echo "GPU Info:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
echo "=============================================="

# Launch vLLM server
python -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --served-model-name "${SERVED_NAME}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --dtype "${DTYPE}" \
    --api-key "${API_KEY}" \
    --trust-remote-code

# Note: The server will run in foreground and log to stdout.
# Use screen/tmux or systemd for production deployments.
