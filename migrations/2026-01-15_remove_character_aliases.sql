-- Migration: Remove aliases column from characters table
-- Date: 2026-01-15
-- Reason: Simplify character model - aliases not needed, just use name variations in character_facts

-- Remove aliases column from characters table
ALTER TABLE characters DROP COLUMN IF EXISTS aliases;

-- Add comment to document the change
COMMENT ON TABLE characters IS 'Character entities extracted from content. Use character_facts array for any name variations or aliases.';
