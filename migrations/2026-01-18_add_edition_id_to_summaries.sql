-- Migration: Add edition_id column to segment_summaries and segment_entities
-- Date: 2026-01-18
-- Purpose: Enable querying summaries/entities by edition without joining through segments

-- Add edition_id to segment_summaries
ALTER TABLE segment_summaries 
ADD COLUMN IF NOT EXISTS edition_id UUID REFERENCES editions(id) ON DELETE CASCADE;

-- Add edition_id to segment_entities
ALTER TABLE segment_entities 
ADD COLUMN IF NOT EXISTS edition_id UUID REFERENCES editions(id) ON DELETE CASCADE;

-- Populate edition_id from segments table
UPDATE segment_summaries ss
SET edition_id = s.edition_id
FROM segments s
WHERE ss.segment_id = s.id
AND ss.edition_id IS NULL;

UPDATE segment_entities se
SET edition_id = s.edition_id
FROM segments s
WHERE se.segment_id = s.id
AND se.edition_id IS NULL;

-- Create indexes for faster queries by edition
CREATE INDEX IF NOT EXISTS idx_segment_summaries_edition_id 
ON segment_summaries(edition_id);

CREATE INDEX IF NOT EXISTS idx_segment_entities_edition_id 
ON segment_entities(edition_id);

-- Verify migration
DO $$
DECLARE
    summary_count INTEGER;
    entity_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO summary_count FROM segment_summaries WHERE edition_id IS NULL;
    SELECT COUNT(*) INTO entity_count FROM segment_entities WHERE edition_id IS NULL;
    
    RAISE NOTICE 'Migration complete:';
    RAISE NOTICE '  segment_summaries with NULL edition_id: %', summary_count;
    RAISE NOTICE '  segment_entities with NULL edition_id: %', entity_count;
    
    IF summary_count > 0 OR entity_count > 0 THEN
        RAISE WARNING 'Some rows still have NULL edition_id - check for orphaned records';
    END IF;
END $$;
