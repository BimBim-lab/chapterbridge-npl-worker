-- Migration: Simplify segment_summaries and segment_entities tables
-- Date: 2026-01-15
-- Description: Remove unused columns and streamline NLP data structure

-- ============================================
-- 1. Simplify segment_summaries table
-- ============================================
-- Keep only: summary_short, summary, events
-- Remove: beats, tone, key_dialogue

ALTER TABLE segment_summaries 
  DROP COLUMN IF EXISTS beats,
  DROP COLUMN IF EXISTS tone,
  DROP COLUMN IF EXISTS key_dialogue;

-- ============================================
-- 2. Simplify segment_entities table
-- ============================================
-- Keep only: characters, locations, keywords, time_context
-- Remove: items, organizations, factions, titles_ranks, skills, 
--         creatures, concepts, relationships, emotions, time_refs
-- Add: time_context

-- Drop unused columns
ALTER TABLE segment_entities
  DROP COLUMN IF EXISTS items,
  DROP COLUMN IF EXISTS organizations,
  DROP COLUMN IF EXISTS factions,
  DROP COLUMN IF EXISTS titles_ranks,
  DROP COLUMN IF EXISTS skills,
  DROP COLUMN IF EXISTS creatures,
  DROP COLUMN IF EXISTS concepts,
  DROP COLUMN IF EXISTS relationships,
  DROP COLUMN IF EXISTS emotions,
  DROP COLUMN IF EXISTS time_refs;

-- Add new time_context column
ALTER TABLE segment_entities
  ADD COLUMN IF NOT EXISTS time_context TEXT NOT NULL DEFAULT 'unknown';

-- ============================================
-- Migration Complete
-- ============================================
-- Final structure:
-- segment_summaries: id, segment_id, summary, summary_short, events, model_version, created_at, updated_at
-- segment_entities: id, segment_id, characters, locations, keywords, time_context, model_version, created_at, updated_at
