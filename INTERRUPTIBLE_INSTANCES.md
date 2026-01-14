# Using Interruptible Instances

This worker is designed to work reliably with **interruptible GPU instances** (RunPod Spot/Interruptible, AWS Spot, GCP Preemptible, etc.).

## What are Interruptible Instances?

Interruptible instances are GPU servers that can be shut down at any time by the cloud provider to reclaim capacity. They're typically **50-80% cheaper** than on-demand instances, making them ideal for batch processing workloads like this NLP worker.

## How This Worker Handles Interruptions

### 1. **Automatic Stale Job Recovery**

When the worker starts, it automatically checks for "stale" jobs that were running when the previous pod was interrupted:

```python
# On startup, worker scans for jobs stuck in "running" status
reset_count = db.reset_stale_jobs(timeout_minutes=3)
```

**What happens:**
- Jobs running longer than `JOB_TIMEOUT_MINUTES` (default: 3 minutes) are automatically detected
- These jobs are marked as `failed` with error message: `"Job timeout after 3 minutes (interrupted/crashed)"`
- Jobs can be retried if they haven't exceeded `MAX_RETRIES_PER_JOB` (default: 2 attempts)

### 2. **Retry Logic**

The worker implements a retry system that respects `attempt` count:

- **Attempt 1-2**: Job will be automatically retried (reset to `queued` → picked up again)
- **Attempt 3+**: Job marked as permanently failed (exceeded max retries)

This prevents infinite retry loops while allowing temporary failures to recover.

### 3. **Stateless Processing**

Each job is self-contained:
- No shared state between jobs
- Each job polls database for segment data, processes, and writes results
- If pod dies mid-processing, next pod picks up from queue

## Configuration

### Environment Variables

```env
# How long before a "running" job is considered stale/interrupted
JOB_TIMEOUT_MINUTES=3

# Maximum retry attempts before giving up
MAX_RETRIES_PER_JOB=2

# Model timeout per job (should be less than JOB_TIMEOUT_MINUTES)
MODEL_TIMEOUT_SECONDS=180  # 3 minutes
```

### Recommended Settings for Interruptible Instances

| Variable | Recommended Value | Reason |
|----------|------------------|---------|
| `JOB_TIMEOUT_MINUTES` | `3` | Most NLP jobs finish in 20-60 seconds. 3min is enough buffer for long texts. |
| `MAX_RETRIES_PER_JOB` | `2-3` | Allows recovery from transient failures without infinite loops. |
| `MODEL_TIMEOUT_SECONDS` | `180` (3min) | Prevents hanging on individual API calls. |
| `POLL_SECONDS` | `3` | Fast polling ensures new pod picks up work quickly after interruption. |

## Cost Savings Example

**On-demand A5000 (24GB):** $0.60/hour  
**Interruptible A5000:** $0.15/hour  
**Savings:** 75% ($0.45/hour)

For 100 hours of processing:
- On-demand: $60
- Interruptible: $15
- **You save $45**

Even if pods are interrupted 5-10 times and jobs need to retry, the cost savings far exceed the overhead.

## RunPod Setup for Interruptible

1. **Create Pod:**
   - Choose "Spot/Interruptible" instance type
   - Select GPU: RTX A5000 (24GB) or higher
   - Set Docker image: `runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04`

2. **Configure Environment Variables:**
   Add all required env vars in Pod Settings → Environment Variables:
   ```
   SUPABASE_URL=https://...
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   R2_ENDPOINT=https://...
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_BUCKET=chapterbridge-data
   VLLM_BASE_URL=http://localhost:8000/v1
   VLLM_API_KEY=token-anything
   VLLM_MODEL=qwen2.5-7b
   MODEL_VERSION=qwen2.5-7b-awq_nlp_pack_v2_no_cleaned_text
   JOB_TIMEOUT_MINUTES=3
   MAX_RETRIES_PER_JOB=2
   ```

3. **Set Start Command:**
   ```bash
   cd /workspace && git clone https://github.com/BimBim-lab/chapterbridge-npl-worker.git && cd chapterbridge-npl-worker && pip install -r requirements.txt && ./serve_model.sh & sleep 30 && python -m nlp_worker.main
   ```

   This command:
   - Clones the repo
   - Installs dependencies
   - Starts vLLM server in background
   - Waits 30s for model to load
   - Starts NLP worker

## Monitoring Interruptions

Check worker logs for stale job recovery:

```
2026-01-14 10:05:23 - nlp_worker.main - INFO - NLP Pack Worker Starting
2026-01-14 10:05:23 - nlp_worker.main - INFO - Checking for stale running jobs (timeout: 3min)...
2026-01-14 10:05:24 - nlp_worker.supabase_client - WARNING - Job abc-123 reset from stale running state (attempt 1/2)
2026-01-14 10:05:24 - nlp_worker.main - INFO - Reset 1 stale jobs from previous run
```

This indicates the worker detected and recovered from a previous interruption.

## Best Practices

1. **Use appropriate timeouts:** 
   - Set `JOB_TIMEOUT_MINUTES` high enough to cover 99% of jobs
   - But low enough to detect interruptions quickly (3min is good default)

2. **Monitor retry counts:**
   - Check `pipeline_jobs.attempt` field in database
   - If many jobs hit max retries, may need to increase `MAX_RETRIES_PER_JOB` or investigate underlying issues

3. **Combine with on-demand for critical work:**
   - Use interruptible for bulk processing (90% of jobs)
   - Use on-demand for time-sensitive or high-priority jobs

4. **Queue management:**
   - Enqueue large batches (100-1000 jobs)
   - Worker will process continuously, surviving multiple interruptions
   - Each new pod picks up from where the previous one left off

## FAQ

**Q: What happens if a job is interrupted mid-processing?**  
A: The job is marked as failed after `JOB_TIMEOUT_MINUTES`. If it hasn't exceeded `MAX_RETRIES_PER_JOB`, it will be retried by the next worker that starts.

**Q: Will I lose progress on partial writes?**  
A: No. The worker uses database transactions and only commits complete outputs. Partial writes are rolled back.

**Q: How often are pods interrupted?**  
A: Varies by provider and demand. Typically 1-5 times per 24 hours. Each interruption causes 1-3 minute downtime while new pod starts.

**Q: Can I use this with always-on instances?**  
A: Yes! The stale job recovery also helps with crashes, network issues, or manual restarts. It's a general robustness feature.

**Q: What if all jobs fail with "Max retries exceeded"?**  
A: Check worker logs for underlying errors. Common causes:
- vLLM server not starting properly
- Database connection issues
- R2 storage problems
- Model producing invalid JSON (need prompt tuning)

Fix the underlying issue and re-enqueue failed jobs with:
```bash
python -m nlp_worker.enqueue --force --work-id=<work-uuid>
```
