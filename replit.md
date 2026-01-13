# ChapterBridge NLP Pack Worker

## Overview
A Python GPU worker for ChapterBridge that processes story segments through a Qwen 7B language model to extract cleaned text, summaries, entities, and character updates.

## Project Architecture

```
nlp_worker/
├── __init__.py              # Package init
├── main.py                  # Daemon poller with dry-run mode
├── enqueue.py               # Job enqueue CLI script
├── supabase_client.py       # Supabase database operations
├── r2_client.py             # Cloudflare R2 storage with retry logic
├── qwen_client.py           # vLLM OpenAI-compatible client with retry/repair
├── schema.py                # Pydantic models for validation + normalization
├── character_merge.py       # Character table merge with alias matching
├── key_builder.py           # Deterministic R2 key generation
├── utils.py                 # Logging, retries, hashing, text analysis
└── text_extractors/
    ├── __init__.py
    ├── subtitle_srt.py      # Anime subtitle (SRT/VTT) extraction
    ├── novel_html.py        # Novel HTML text extraction
    └── manhwa_ocr.py        # Manhwa OCR JSON extraction
```

## Key Features

### Schema Validation
- Pydantic models ensure all required fields exist with correct types
- All `segment_entities` fields guaranteed to be arrays (never null)
- Auto-repair: If JSON fails validation, tries a repair call

### Partial Idempotency
- Checks for existing outputs before processing
- Only writes missing outputs (cleaned_text, summary, entities)
- `force=true` will overwrite all outputs

### Robust Retry Logic
- Model calls: configurable timeout (180s default) and retries
- R2 operations: 3 retries with exponential backoff
- Handles connection errors, rate limits, and server errors

### Metrics
Each job records detailed stats in `pipeline_jobs.output.stats`:
- Input/output chars, token estimates
- Model latency, retry counts
- Media-specific counts (pages, paragraphs, subtitle blocks)

## Environment Variables Required

```bash
# Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...

# Storage
R2_ENDPOINT=https://accountid.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=chapterbridge-data

# Model Server
VLLM_BASE_URL=http://runpod-ip:8000/v1
VLLM_API_KEY=token-anything
VLLM_MODEL=qwen2.5-7b

# Worker Config
POLL_SECONDS=3
MAX_RETRIES_PER_JOB=2
MODEL_VERSION=qwen2.5-7b-awq_nlp_pack_v1

# Timeout/Retry (optional)
MODEL_TIMEOUT_SECONDS=180
MODEL_MAX_RETRIES=2
R2_MAX_RETRIES=3
```

## Running the Worker

```bash
# Verify setup
python verify_worker.py

# Dry-run (test without writing)
python -m nlp_worker.main --segment-id <uuid> --no-write

# Enqueue jobs for unprocessed segments
python -m nlp_worker.enqueue

# Start worker daemon
python -m nlp_worker.main
```

## R2 Key Format

Cleaned text uses deterministic keys:
```
derived/{media_type}/{work_id}/{edition_id}/{segment_type}-{NNNN}/cleaned.txt
```
Where NNNN is zero-padded segment number (e.g., 13 → 0013)

## External Dependencies
- **Supabase**: PostgreSQL database with ChapterBridge schema
- **Cloudflare R2**: Object storage for assets
- **vLLM**: GPU model server (RunPod or similar) running Qwen2.5-7B-Instruct-AWQ

## Recent Changes
- 2026-01-13: Initial implementation of NLP Pack worker
- 2026-01-13: Added improvements:
  - Pydantic schema validation with auto-repair
  - Robust timeout/retry for model and R2
  - Improved character merge with alias matching + fact dedupe
  - Metrics in pipeline_jobs.output.stats
  - Partial idempotency (write only missing outputs)
  - Dry-run mode for testing
