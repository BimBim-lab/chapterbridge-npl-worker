# Schema Simplification Update Summary

**Date**: January 15, 2026  
**Purpose**: Simplified segment_summaries and segment_entities tables to streamline NLP processing

## Schema Changes

### segment_summaries
**Kept:**
- `summary` (TEXT)
- `summary_short` (TEXT)
- `events` (JSONB array)

**Removed:**
- ~~`beats`~~ (JSONB array)
- ~~`tone`~~ (JSONB object)
- ~~`key_dialogue`~~ (JSONB array)

### segment_entities
**Kept:**
- `characters` (JSONB array)
- `locations` (JSONB array)
- `keywords` (JSONB array)

**Added:**
- `time_context` (TEXT: "present"|"past"|"future"|"mixed"|"unknown")

**Removed:**
- ~~`items`~~ (JSONB array)
- ~~`organizations`~~ (JSONB array)
- ~~`factions`~~ (JSONB array)
- ~~`titles_ranks`~~ (JSONB array)
- ~~`skills`~~ (JSONB array)
- ~~`creatures`~~ (JSONB array)
- ~~`concepts`~~ (JSONB array)
- ~~`relationships`~~ (JSONB array)
- ~~`emotions`~~ (JSONB array)
- ~~`time_refs`~~ (JSONB array)

## Code Changes

### 1. schema.py
- ✅ Removed `ToneModel`, `DialogueModel`, `BeatModel` classes
- ✅ Simplified `SegmentSummaryModel` to only include summary, summary_short, events
- ✅ Simplified `SegmentEntitiesModel` to only include characters, locations, keywords, time_context
- ✅ Added validation for `time_context` field (must be one of valid enum values)
- ✅ Updated `get_vllm_guided_json_schema()` to reflect new structure

### 2. qwen_client.py
- ✅ Updated `build_system_prompt()` to request only simplified fields
- ✅ Removed instructions for deprecated fields (beats, tone, key_dialogue, etc.)
- ✅ Added clear instruction for time_context enum values
- ✅ Updated example output structure in prompt

### 3. supabase_client.py
- ✅ Updated `upsert_segment_summary()` signature - removed beats, key_dialogue, tone parameters
- ✅ Updated `upsert_segment_entities()` to only upsert characters, locations, keywords, time_context
- ✅ Removed handling of deprecated entity fields

### 4. main.py
- ✅ Updated call to `upsert_segment_summary()` to only pass simplified fields
- ✅ No changes needed for `upsert_segment_entities()` call (uses dict parameter)

## Migration Required

Run the migration file to update the database schema:
```sql
-- File: migrations/2026-01-15_simplify_segments.sql
```

This migration will:
1. Drop unused columns from both tables
2. Add `time_context` column to segment_entities
3. Use `IF EXISTS`/`IF NOT EXISTS` for safety

## Testing Recommendations

1. **Run migration first** on Supabase production database
2. **Test with dry-run mode**:
   ```bash
   python -m nlp_worker.main --segment-id <segment_uuid> --dry-run
   ```
3. **Verify model output** contains only new fields
4. **Check database inserts** are successful with simplified schema

## Benefits

- **Reduced complexity**: Fewer fields to extract and validate
- **Cleaner data model**: Focus on core NLP features needed for the application
- **Better performance**: Less data to process and store
- **Easier maintenance**: Simpler schema is easier to understand and modify

## Backward Compatibility

⚠️ **Breaking change**: Old workers using the previous schema will fail after migration.
- Ensure all worker instances are updated before running the migration
- Or run migration first (columns will be dropped but won't break new code)
