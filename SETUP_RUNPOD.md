# RunPod Setup Commands - Fresh Pod (Updated 2026-01-18)

**Prerequisites:** RunPod pod dengan GPU (A40/A100), image `runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04`

---

## 1. Clone Repository & Install
```bash
cd /workspace
git clone https://github.com/BimBim-lab/chapterbridge-npl-worker.git
cd chapterbridge-npl-worker
pip install -r requirements.txt
```

## 2. Create .env File
⚠️ **EDIT CREDENTIALS** sebelum run!

```bash
cat > .env << 'EOF'
# ===== Database =====
SUPABASE_URL=https://czkmfderwtnltzlytzig.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.YOUR_KEY_HERE

# ===== R2 Storage =====
R2_ENDPOINT=https://7179c252774c3316da886216d661ac21.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=YOUR_R2_ACCESS_KEY
R2_SECRET_ACCESS_KEY=YOUR_R2_SECRET_KEY
R2_BUCKET=chapterbridge-data
R2_CUSTOM_DOMAIN=https://assets.chapterbridge.com

# ===== vLLM Server =====
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_API_KEY=token-anything
VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct

# ===== Worker Settings =====
NUM_WORKERS=8
POLL_SECONDS=3
MAX_RETRIES_PER_JOB=2
MODEL_VERSION=qwen2.5-7b-nlp_pack_v2_no_aliases
JOB_TIMEOUT_MINUTES=3

# ===== Timeouts & Retries =====
MODEL_TIMEOUT_SECONDS=180
MODEL_MAX_RETRIES=2
R2_MAX_RETRIES=3
R2_RETRY_DELAY=1.0
EOF
```

Verify .env:
```bash
grep -E "SUPABASE_SERVICE_ROLE_KEY|R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY" .env
```

## 3. Start vLLM Server (Background)
```bash
nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --dtype float16 \
  --gpu-memory-utilization 0.9 \
  --port 8000 \
  --api-key token-anything > vllm.log 2>&1 &
```

Monitor loading (wait ~2-3 minutes):
```bash
tail -f vllm.log
# Press Ctrl+C when you see "Application startup complete"
```

## 4. Verify vLLM Ready
```bash
curl -H "Authorization: Bearer token-anything" http://localhost:8000/v1/models
```

Expected output: `{"data":[{"id":"Qwen/Qwen2.5-7B-Instruct",...}]}`

## 5. Start Worker with Auto-Restart Loop
```bash
nohup bash -c 'while true; do python3 run_worker.py; sleep 5; done' > worker.log 2>&1 &
```

## 6. Monitor Worker
```bash
# Real-time logs
tail -f worker.log

# Check if processing jobs
tail -f worker.log | grep -E "Processing job|Downloaded|completed"
```

---

## 7. Quick Status Dashboard
```bash
clear
echo "========== WORKER STATUS =========="
ps aux | grep 'python3 run_worker.py' | grep -v grep | awk '{print "PID:", $2, "CPU:", $3"%", "RAM:", $4"%", "TIME:", $10}'
echo ""
echo "========== NUM_WORKERS =========="
grep NUM_WORKERS .env
echo ""
echo "========== GPU STATUS =========="
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | awk -F', ' '{printf "GPU: %d%% | VRAM: %dMB/%dMB (%.1f%%)\n", $1, $2, $3, ($2/$3)*100}'
```

## 8. Troubleshooting

**vLLM not starting:**
```bash
# Check vLLM log
tail -50 vllm.log

# Kill and restart
pkill -f vllm
nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --dtype float16 \
  --gpu-memory-utilization 0.9 \
  --port 8000 \
  --api-key token-anything > vllm.log 2>&1 &
```

**Worker not processing jobs:**
```bash
# Check worker log for errors
tail -100 worker.log | grep -E "ERROR|exception|failed"

# Check if jobs in queue (manual test from local machine)
python -m nlp_worker.enqueue --work-id YOUR_WORK_ID --limit 10

# Restart worker
pkill -f run_worker.py
nohup bash -c 'while true; do python3 run_worker.py; sleep 5; done' > worker.log 2>&1 &
```

**Update code from GitHub:**
```bash
cd /workspace/chapterbridge-npl-worker
git pull origin main
pkill -f run_worker.py
nohup bash -c 'while true; do python3 run_worker.py; sleep 5; done' > worker.log 2>&1 &
```

**Clean restart everything:**
```bash
# Kill all processes
pkill -f vllm
pkill -f run_worker.py

# Wait 5 seconds
sleep 5

# Start vLLM
nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --dtype float16 \
  --gpu-memory-utilization 0.9 \
  --port 8000 \
  --api-key token-anything > vllm.log 2>&1 &

# Wait for vLLM ready (2-3 min)
sleep 120

# Test vLLM
curl -H "Authorization: Bearer token-anything" http://localhost:8000/v1/models

# Start worker
nohup bash -c 'while true; do python3 run_worker.py; sleep 5; done' > worker.log 2>&1 &
```

---

## 9. Expected Behavior

**Successful Startup:**
- vLLM loads model in ~2-3 minutes
- Worker starts 8 concurrent threads
- Logs show: `"Processing job XXX for segment YYY"`
- GPU VRAM ~42-44GB used (91-95%)
- Worker processes 1-3 jobs/minute depending on content length

**Normal Logs:**
```
2026-01-18 10:23:45 - INFO - Processing job abc123 for segment def456
2026-01-18 10:23:46 - INFO - Downloaded 15234 bytes from raw/novel/...
2026-01-18 10:23:47 - INFO - Extracted 8715 chars of source text
2026-01-18 10:23:48 - INFO - Sending 8715 chars to model for novel
2026-01-18 10:24:12 - INFO - Model processing completed (latency: 24000ms)
2026-01-18 10:24:13 - INFO - Upserted segment_summaries for def456
2026-01-18 10:24:14 - INFO - Job abc123 completed successfully
```
