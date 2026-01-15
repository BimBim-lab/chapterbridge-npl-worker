# RunPod Setup Commands - Fresh Pod

## 1. Clone Repository
```bash
cd /workspace
git clone https://github.com/BimBim-lab/chapterbridge-npl-worker.git
cd chapterbridge-npl-worker
chmod +x *.sh
```

## 2. Install Dependencies
```bash
pip install -r requirements.txt
```

## 3. Create .env File
```bash
cat > .env << 'EOF'
# Supabase
SUPABASE_URL=https://czkmfderwtnltzlytzig.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<YOUR_SERVICE_ROLE_KEY>

# R2 Storage
R2_ENDPOINT=https://1234567890abcdef.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<YOUR_ACCESS_KEY>
R2_SECRET_ACCESS_KEY=<YOUR_SECRET_KEY>
R2_BUCKET=chapterbridge-data

# vLLM
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_MODEL=qwen2.5-7b

# Worker Config
NUM_WORKERS=8
MAX_JOBS_PER_RESTART=100
POLL_SECONDS=3
MAX_RETRIES_PER_JOB=2
JOB_TIMEOUT_MINUTES=3
MODEL_VERSION=qwen2.5-7b-awq_nlp_pack_v1
EOF
```

## 4. Fix .env Line Endings
```bash
sed -i 's/\r$//' .env
```

## 5. Start vLLM Server (Background)
```bash
nohup bash serve_model.sh > /workspace/vllm.log 2>&1 &
```

## 6. Wait for vLLM Ready (30-60s)
```bash
sleep 60
tail -20 /workspace/vllm.log
```

## 7. Test vLLM
```bash
curl http://localhost:8000/health
```

## 8. Start Worker with Auto-Restart
```bash
nohup bash start_worker_loop.sh > /dev/null 2>&1 &
```

## 9. Monitor
```bash
tail -f /workspace/worker.log
```

## Quick Dashboard
```bash
clear && echo "=== WORKER ===" && ps aux | grep 'python3 -m nlp_worker' | grep -v grep | awk '{print "PID:", $2, "CPU:", $3"%", "RAM:", $4"%"}' && echo -e "\n=== GPU ===" && nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | awk -F', ' '{printf "GPU: %d%% | VRAM: %dMB/%dMB\n", $1, $2, $3}' && echo -e "\n=== LOGS ===" && tail -10 /workspace/worker.log
```
