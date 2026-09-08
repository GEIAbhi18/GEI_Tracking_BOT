-- =============================================================================
-- Migration 09: Facilities Tracker - Planned Date & Completion Dates
-- =============================================================================
-- Renames Target Date to Planned Date and adds Estimated Completion Date
-- and Actual Completion Date to row_cache.
-- =============================================================================

ALTER TABLE row_cache ADD COLUMN IF NOT EXISTS planned_date TEXT;
ALTER TABLE row_cache ADD COLUMN IF NOT EXISTS estimated_completion_date TEXT;
ALTER TABLE row_cache ADD COLUMN IF NOT EXISTS actual_completion_date TEXT;

-- Backfill planned_date from target_date if planned_date is NULL
UPDATE row_cache
SET planned_date = target_date
WHERE planned_date IS NULL AND target_date IS NOT NULL;

-- Index for filtering on planned_date
CREATE INDEX IF NOT EXISTS idx_row_cache_planned_date ON row_cache(planned_date);
