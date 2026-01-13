# 🚀 Panduan Deploy ke RunPod

Panduan lengkap untuk deploy ChapterBridge NLP Worker ke RunPod dengan GPU.

## 📋 Prerequisites

1. **Akun RunPod**: Daftar di [runpod.io](https://runpod.io)
2. **Credit/Balance**: Minimal $10 untuk testing
3. **Environment Variables**: Sudah disiapkan (lihat `.env.example`)

---

## 🎯 Langkah 1: Setup vLLM Server (GPU Pod)

### 1.1 Buat GPU Pod untuk vLLM Server

1. Login ke [RunPod Console](https://www.runpod.io/console/pods)
2. Klik **"+ Deploy"** atau **"Deploy Pod"**
3. Pilih **GPU Type**:
   - **Minimum**: RTX 4090 (24GB VRAM) - $0.69/hour
   - **Recommended**: A6000 (48GB VRAM) - $0.79/hour
   - **Optimal**: A100 (40GB/80GB) - $1.89/hour

4. **Pod Configuration**:
   - Template: **RunPod PyTorch 2.x** atau **Custom**
   - Volume Disk: 50GB (untuk model download)
   - Expose HTTP Ports: **8000, 22**
   - Container Disk: 20GB minimum

5. Klik **"Deploy On-Demand"** atau **"Deploy Spot"** (lebih murah tapi bisa interrupted)

### 1.2 Connect ke GPU Pod

Setelah pod running, catat:
- **Pod ID**: `xxxxx-xxxxxxxx`
- **SSH Command**: Tersedia di pod details
- **Public IP**: Akan digunakan untuk `VLLM_BASE_URL`

### 1.3 Install vLLM di GPU Pod

SSH ke pod:
```bash
# Gunakan SSH command dari RunPod console
ssh root@<pod-ip> -p <ssh-port>
```

Install vLLM dan dependencies:
```bash
# Update pip
pip install --upgrade pip

# Install vLLM dengan CUDA support
pip install vllm torch

# Verify installation
python -c "import vllm; print(vllm.__version__)"
```

### 1.4 Download Model dan Start vLLM Server

Buat script `serve_model.sh`:
```bash
#!/bin/bash

# Download model dari HuggingFace (otomatis cache)
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ \
  --quantization awq \
  --dtype auto \
  --max-model-len 8192 \
  --host 0.0.0.0 \
  --port 8000 \
  --api-key token-anything
```

Jalankan server:
```bash
chmod +x serve_model.sh
./serve_model.sh
```

**Catatan**: 
- Download model pertama kali akan memakan waktu 5-10 menit
- Model akan di-cache di `/root/.cache/huggingface`
- Server siap saat melihat log: `Uvicorn running on http://0.0.0.0:8000`

### 1.5 Test vLLM Server

Dari terminal lokal, test dengan curl:
```bash
curl http://<your-pod-ip>:8000/v1/models
```

Atau test dengan Python:
```python
from openai import OpenAI
client = OpenAI(
    base_url="http://<your-pod-ip>:8000/v1",
    api_key="token-anything"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct-AWQ",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

**Catat Public IP** ini untuk digunakan di Step 2!

---

## 🔧 Langkah 2: Setup Worker Pod (CPU Pod)

### 2.1 Buat CPU Pod untuk Worker

1. Kembali ke RunPod Console
2. Klik **"+ Deploy"** lagi
3. **Pilih CPU Pod** (lebih murah untuk worker):
   - CPU: 4 vCPU minimum
   - RAM: 8GB minimum
   - Template: **Ubuntu** atau **Python**
   - Volume: 10GB

4. **Expose Ports**: 22 (SSH)
5. Deploy pod

### 2.2 Connect ke Worker Pod

```bash
ssh root@<worker-pod-ip> -p <ssh-port>
```

### 2.3 Install Dependencies

```bash
# Update system
apt-get update && apt-get install -y git python3 python3-pip

# Clone repository (atau upload via SCP)
git clone https://github.com/your-repo/chapterbridge-npl-worker.git
cd chapterbridge-npl-worker

# Install Python packages
pip3 install -r requirements.txt
```

### 2.4 Setup Environment Variables

Buat file `.env`:
```bash
nano .env
```

Isi dengan environment variables (sesuaikan dengan credentials Anda):
```bash
# Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...

# Cloudflare R2
R2_ENDPOINT=https://your-account-id.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your-r2-access-key
R2_SECRET_ACCESS_KEY=your-r2-secret-key
R2_BUCKET=chapterbridge-data

# vLLM Server (GUNAKAN IP GPU POD DARI STEP 1!)
VLLM_BASE_URL=http://<gpu-pod-ip>:8000/v1
VLLM_API_KEY=token-anything
VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ

# Worker Settings
POLL_SECONDS=3
MAX_RETRIES_PER_JOB=2
MODEL_VERSION=qwen2.5-7b-awq_nlp_pack_v1
```

Load environment variables:
```bash
export $(cat .env | xargs)
```

### 2.5 Verify Worker Setup

Test koneksi ke semua services:
```bash
python3 verify_worker.py
```

Output yang diharapkan:
```
✓ Supabase connection: OK
✓ R2 connection: OK
✓ vLLM server: OK
✓ All systems ready!
```

### 2.6 Start Worker

Run worker in production:
```bash
# Foreground (untuk testing)
python3 -m nlp_worker.main

# Background dengan nohup
nohup python3 -m nlp_worker.main > worker.log 2>&1 &

# Atau menggunakan screen (recommended)
screen -S nlp-worker
python3 -m nlp_worker.main
# Ctrl+A, D untuk detach
```

Untuk melihat logs:
```bash
tail -f worker.log
# atau
screen -r nlp-worker
```

---

## 📊 Langkah 3: Monitoring

### 3.1 Check Worker Status

```bash
# Lihat logs
tail -f worker.log

# Check process
ps aux | grep nlp_worker

# Check GPU utilization (di GPU pod)
nvidia-smi
```

### 3.2 Monitor Database

Check job status di Supabase:
```sql
SELECT 
  id, 
  status, 
  job_type, 
  attempt, 
  created_at, 
  started_at,
  completed_at,
  output->'stats' as stats
FROM pipeline_jobs
WHERE job_type = 'summarize'
ORDER BY created_at DESC
LIMIT 20;
```

### 3.3 Cost Management

**GPU Pod (vLLM Server)**:
- RTX 4090: ~$0.69/hour = ~$496/month
- Spot instance: 50-70% lebih murah (tapi bisa interrupted)

**CPU Pod (Worker)**:
- 4 vCPU, 8GB RAM: ~$0.10/hour = ~$72/month

**Tips hemat**:
- Gunakan Spot instances
- Stop pod saat tidak digunakan
- Set auto-stop saat idle
- Monitor credit usage di RunPod dashboard

---

## 🔄 Langkah 4: Auto-Restart & Production Setup

### 4.1 Setup Systemd Service (Alternative to screen)

Buat file service:
```bash
nano /etc/systemd/system/nlp-worker.service
```

Isi:
```ini
[Unit]
Description=ChapterBridge NLP Worker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/chapterbridge-npl-worker
EnvironmentFile=/root/chapterbridge-npl-worker/.env
ExecStart=/usr/bin/python3 -m nlp_worker.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable dan start:
```bash
systemctl daemon-reload
systemctl enable nlp-worker
systemctl start nlp-worker

# Check status
systemctl status nlp-worker

# View logs
journalctl -u nlp-worker -f
```

### 4.2 Setup Docker (Optional)

Buat `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "nlp_worker.main"]
```

Build dan run:
```bash
docker build -t chapterbridge-worker .
docker run -d --env-file .env --name nlp-worker chapterbridge-worker
```

---

## 🐛 Troubleshooting

### Issue 1: Worker tidak bisa connect ke vLLM
```bash
# Check apakah vLLM server running
curl http://<gpu-pod-ip>:8000/v1/models

# Check firewall di GPU pod
ufw status

# Pastikan port 8000 exposed di RunPod settings
```

### Issue 2: Out of Memory di GPU
```bash
# Reduce max model length
--max-model-len 4096  # instead of 8192

# Use smaller batch size
--max-num-seqs 4
```

### Issue 3: Worker stuck/hanging
```bash
# Check logs
tail -f worker.log

# Restart worker
systemctl restart nlp-worker

# Check database connection
python3 -c "from nlp_worker.supabase_client import get_supabase_client; get_supabase_client()"
```

### Issue 4: Job stuck in 'running' status
```sql
-- Reset stuck jobs (di Supabase SQL editor)
UPDATE pipeline_jobs 
SET status = 'queued', started_at = NULL, attempt = 0
WHERE status = 'running' 
  AND started_at < NOW() - INTERVAL '1 hour';
```

---

## 📞 Support & References

- **RunPod Docs**: https://docs.runpod.io/
- **vLLM Docs**: https://docs.vllm.ai/
- **Qwen Model**: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-AWQ

Jika ada masalah, check logs terlebih dahulu dan pastikan semua environment variables sudah benar!
