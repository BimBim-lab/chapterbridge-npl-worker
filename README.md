# ChapterBridge NLP Pack Worker

A Python GPU worker that processes story segments through a Qwen 7B language model to extract:
- Cleaned text (noise/watermark removal)
- Narrative summaries and story beats
- Entity extraction (characters, locations, items, etc.)
- Character database updates (novels only)

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   Supabase DB   │────▶│  NLP Worker  │────▶│   vLLM API  │
│  (pipeline_jobs)│     │  (this code) │     │  (Qwen 7B)  │
└─────────────────┘     └──────┬───────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │ Cloudflare R2│
                        │   (storage)  │
                        └──────────────┘
```

## Requirements

- Python 3.11+
- Access to Supabase project with ChapterBridge schema
- Cloudflare R2 bucket with read/write access
- vLLM server running Qwen model (RunPod or similar GPU instance)

## Environment Variables

Create a `.env` file or set these in your environment:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Cloudflare R2
R2_ENDPOINT=https://accountid.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_BUCKET=chapterbridge-data

# vLLM Server
VLLM_BASE_URL=http://your-runpod-ip:8000/v1
VLLM_API_KEY=token-anything
VLLM_MODEL=qwen2.5-7b

# Worker Settings
POLL_SECONDS=3
MAX_RETRIES_PER_JOB=2
MODEL_VERSION=qwen2.5-7b-awq_nlp_pack_v1
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Starting the vLLM Server (RunPod)

1. Create a RunPod instance with at least 24GB VRAM (RTX 4090, A6000, or similar)

2. SSH into your pod and install vLLM:
   ```bash
   pip install vllm
   ```

3. Copy and run the serve script:
   ```bash
   chmod +x serve_model.sh
   ./serve_model.sh
   ```

4. Note your pod's public IP and port (default 8000)

5. Set `VLLM_BASE_URL=http://<your-pod-ip>:8000/v1` in your worker environment

## Running the Worker

### Enqueue Jobs

First, create jobs for segments that need processing:

```bash
# Enqueue all missing segments
python -m nlp_worker.enqueue

# Dry run - see what would be enqueued
python -m nlp_worker.enqueue --dry-run

# Limit to specific work
python -m nlp_worker.enqueue --work-id <uuid>

# Limit to specific media type
python -m nlp_worker.enqueue --media-type novel

# Force reprocessing
python -m nlp_worker.enqueue --force --limit 10
```

### Run the Worker Daemon

```bash
# Start the worker (runs forever)
python -m nlp_worker.main
```

The worker will:
1. Poll Supabase for queued `summarize` jobs with `task=nlp_pack_v1`
2. Download source content from R2 (HTML, subtitles, or OCR JSON)
3. Extract clean text locally
4. Send to Qwen model for analysis
5. Write results back to R2 and Supabase

## Project Structure

```
nlp_worker/
├── main.py              # Daemon poller
├── enqueue.py           # Job enqueue script
├── supabase_client.py   # Database operations
├── r2_client.py         # R2 storage client
├── qwen_client.py       # vLLM API client
├── schema.py            # JSON schema for model output
├── character_merge.py   # Character table merge logic
├── key_builder.py       # Deterministic R2 key generation
├── utils.py             # Logging, retries, hashing
└── text_extractors/
    ├── subtitle_srt.py  # Anime subtitle extraction
    ├── novel_html.py    # Novel HTML extraction
    └── manhwa_ocr.py    # Manhwa OCR JSON extraction
```

## Job Contract

Jobs are stored in `pipeline_jobs` table:

```json
{
  "job_type": "summarize",
  "status": "queued",
  "segment_id": "<uuid>",
  "input": {
    "task": "nlp_pack_v1",
    "force": false
  }
}
```

## Output Locations

| Output | Location |
|--------|----------|
| Cleaned text | R2: `derived/{media}/{work_id}/{edition_id}/{type}-{NNNN}/cleaned.txt` |
| Summary | `segment_summaries` table |
| Entities | `segment_entities` table |
| Characters | `characters` table (novels only) |

## Idempotency

The worker checks for existing outputs before processing:
- If all outputs exist and `force=false`: job is skipped
- If some outputs exist: only missing outputs are written
- `force=true` will reprocess and overwrite

## Error Handling

- Jobs retry up to `MAX_RETRIES_PER_JOB` times
- Failed jobs are marked with full stack trace in `error` column
- Worker continues polling after individual job failures

## Development

```bash
# Run tests (if available)
pytest tests/

# Type checking
mypy nlp_worker/
```
