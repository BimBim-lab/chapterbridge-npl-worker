# ChapterBridge NLP Pack Worker

## Overview
A Python GPU worker for ChapterBridge that processes story segments through a Qwen 7B language model to extract cleaned text, summaries, entities, and character updates.

## Project Architecture

```
nlp_worker/
├── __init__.py              # Package init
├── main.py                  # Daemon poller (entry point)
├── enqueue.py               # Job enqueue CLI script
├── supabase_client.py       # Supabase database operations
├── r2_client.py             # Cloudflare R2 storage client
├── qwen_client.py           # vLLM OpenAI-compatible client
├── schema.py                # JSON schema for model output
├── character_merge.py       # Character table merge logic
├── key_builder.py           # Deterministic R2 key generation
├── utils.py                 # Logging, retries, hashing
└── text_extractors/
    ├── __init__.py
    ├── subtitle_srt.py      # Anime subtitle (SRT/VTT) extraction
    ├── novel_html.py        # Novel HTML text extraction
    └── manhwa_ocr.py        # Manhwa OCR JSON extraction
```

## Key Components

### Worker Flow
1. Polls `pipeline_jobs` table for `job_type='summarize'` with `task='nlp_pack_v1'`
2. Downloads source content from R2 (HTML, subtitles, or OCR JSON)
3. Extracts clean text locally based on media type
4. Sends to Qwen model for structured NLP analysis
5. Writes results: cleaned text to R2, summaries/entities to Supabase

### Media Type Handling
- **Anime**: SRT/VTT subtitle parsing, noise removal
- **Novel**: HTML parsing with boilerplate removal
- **Manhwa**: OCR JSON aggregation across pages

### Idempotency
Worker checks for existing outputs before processing and skips if all exist (unless `force=true`)

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
```

## Running the Worker

```bash
# Verify setup
python verify_worker.py

# Enqueue jobs for unprocessed segments
python -m nlp_worker.enqueue

# Start worker daemon
python -m nlp_worker.main
```

## External Dependencies
- **Supabase**: PostgreSQL database with ChapterBridge schema
- **Cloudflare R2**: Object storage for assets
- **vLLM**: GPU model server (RunPod or similar) running Qwen2.5-7B-Instruct-AWQ

## Recent Changes
- 2026-01-13: Initial implementation of NLP Pack worker
  - Complete pipeline job processing for summarize tasks
  - Text extractors for all media types
  - Structured JSON output with schema validation
  - Character merge logic for novels
