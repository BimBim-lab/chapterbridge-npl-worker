# ChapterBridge NLP Pack Worker

A Python GPU worker that processes story segments through a Qwen 7B language model to extract:
- Cleaned text (noise/watermark removal)
- Narrative summaries and story beats
- Entity extraction (characters, locations, items, etc.)
- Character database updates (novels only)

## Features

- **Strict Schema Validation**: Pydantic models ensure all required fields exist with correct types
- **Auto-repair**: Attempts JSON repair if model output fails validation
- **Partial Idempotency**: Only writes missing outputs, skips existing ones
- **Robust Retry Logic**: Configurable retries with exponential backoff for model and R2 operations
- **Metrics & Logging**: Detailed stats in `pipeline_jobs.output.stats`
- **Dry-run Mode**: Test processing without writing to DB/R2

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

```bash
# Database
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

# Timeout/Retry Settings (optional)
MODEL_TIMEOUT_SECONDS=180
MODEL_MAX_RETRIES=2
R2_MAX_RETRIES=3
R2_RETRY_DELAY=1.0
```

## Installation

```bash
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

### Dry-Run Mode (Testing)

Test processing a specific segment without writing to DB/R2:

```bash
python -m nlp_worker.main --segment-id <uuid> --no-write
```

This will:
- Download source content from R2
- Extract text locally
- Call the model
- Validate and normalize output
- Print stats summary without writing anything

### Enqueue Jobs

Create jobs for segments that need processing:

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
python -m nlp_worker.main
```

The worker will:
1. Poll Supabase for queued `summarize` jobs with `task=nlp_pack_v1`
2. Download source content from R2 (HTML, subtitles, or OCR JSON)
3. Extract clean text locally
4. Send to Qwen model for analysis with structured JSON schema
5. Validate and normalize output with auto-repair on failure
6. Write only missing outputs (partial idempotency)
7. Log detailed metrics to `pipeline_jobs.output.stats`

## Output Locations

| Output | Location |
|--------|----------|
| Cleaned text | R2: `derived/{media}/{work_id}/{edition_id}/{segment_type}-{NNNN}/cleaned.txt` |
| Summary | `segment_summaries` table |
| Entities | `segment_entities` table |
| Characters | `characters` table (novels only) |

## R2 Key Format

Cleaned text uses deterministic keys:
```
derived/{media_type}/{work_id}/{edition_id}/{segment_type}-{NNNN}/cleaned.txt
```
Where:
- `media_type`: novel, manhwa, or anime
- `segment_type`: chapter or episode (from DB)
- `NNNN`: Zero-padded segment number (e.g., 13 → 0013)

## Metrics

Each job records stats in `pipeline_jobs.output.stats`:

```json
{
  "media_type": "novel",
  "segment_type": "chapter",
  "segment_number": 42,
  "input_chars": 15234,
  "input_tokens_est": 3808,
  "output_chars": 8521,
  "model_latency_ms": 4523,
  "retries_count": 0,
  "paragraph_count": 45,
  "repair_attempted": false,
  "repair_succeeded": false
}
```

## Schema Normalization

The worker uses Pydantic models to ensure all output fields are properly typed:
- All `segment_entities` fields are guaranteed to be arrays (never null)
- All `segment_summary` fields have defaults
- Invalid JSON triggers auto-repair with a second model call

## Idempotency

- Checks for existing: cleaned_text asset, segment_summaries row, segment_entities row
- If all exist and `force=false`: job is skipped with `output.skipped=true`
- If some exist: only missing outputs are written
- `force=true` will reprocess and overwrite all outputs

## Error Handling

- Model calls retry up to `MODEL_MAX_RETRIES` times with exponential backoff
- R2 operations retry up to `R2_MAX_RETRIES` times
- Invalid JSON triggers one repair attempt
- Jobs retry up to `MAX_RETRIES_PER_JOB` times
- Failed jobs are marked with full stack trace in `error` column

## Project Structure

```
nlp_worker/
├── main.py              # Daemon poller + dry-run mode
├── enqueue.py           # Job enqueue script
├── supabase_client.py   # Database operations
├── r2_client.py         # R2 storage with retry logic
├── qwen_client.py       # vLLM client with retry + repair
├── schema.py            # Pydantic models + validation
├── character_merge.py   # Character merge with alias matching
├── key_builder.py       # Deterministic R2 key generation
├── utils.py             # Logging, retries, text analysis
└── text_extractors/
    ├── subtitle_srt.py  # Anime subtitle extraction
    ├── novel_html.py    # Novel HTML extraction
    └── manhwa_ocr.py    # Manhwa OCR JSON extraction
```
