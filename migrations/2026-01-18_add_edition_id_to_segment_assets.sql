-- Migration: Add edition_id column to segment_assets
-- Date: 2026-01-18
-- Purpose: Enable querying assets by edition without joining through segments

-- Add edition_id to segment_assets
ALTER TABLE segment_assets 
ADD COLUMN IF NOT EXISTS edition_id UUID REFERENCES editions(id) ON DELETE CASCADE;

-- Populate edition_id from segments table
UPDATE segment_assets sa
SET edition_id = s.edition_id
FROM segments s
WHERE sa.segment_id = s.id
AND sa.edition_id IS NULL;

-- Create index for faster queries by edition
CREATE INDEX IF NOT EXISTS idx_segment_assets_edition_id 
ON segment_assets(edition_id);

-- Verify migration
DO $$
DECLARE
    null_count INTEGER;
    total_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_count FROM segment_assets;
    SELECT COUNT(*) INTO null_count FROM segment_assets WHERE edition_id IS NULL;
    
    RAISE NOTICE 'Migration complete:';
    RAISE NOTICE '  Total segment_assets rows: %', total_count;
    RAISE NOTICE '  Rows with NULL edition_id: %', null_count;
    
    IF null_count > 0 THEN
        RAISE WARNING 'Some rows still have NULL edition_id - check for orphaned records';
    ELSE
        RAISE NOTICE '  ✓ All rows have edition_id populated';
    END IF;
END $$;
