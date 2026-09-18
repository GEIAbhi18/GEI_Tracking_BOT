-- =============================================================================
-- Migration 12: Elara Home Attachments Schema
-- =============================================================================
-- Description:
-- 1. Adds 'attachments' JSONB column to 'elara_tasks' for instant task-level access
--    and Kanban board sync (consistent with 'comments' JSONB column).
-- 2. Creates dedicated 'elara_attachments' table for full historical audit trail,
--    mirrored after 'facilities_attachments'.
-- 3. Creates index on 'elara_attachments.task_id'.
-- =============================================================================

-- 1. Add attachments column to elara_tasks table
ALTER TABLE elara_tasks 
ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]'::jsonb;

-- Ensure existing rows have empty array instead of NULL
UPDATE elara_tasks 
SET attachments = '[]'::jsonb 
WHERE attachments IS NULL;

-- 2. Create elara_attachments table
CREATE TABLE IF NOT EXISTS elara_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_name TEXT,
    file_type TEXT,
    uploaded_by TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create index for fast lookups by task_id
CREATE INDEX IF NOT EXISTS idx_elara_attachments_task_id 
    ON elara_attachments(task_id);

-- Note: If you use a dedicated Supabase Storage bucket for Elara Home,
-- ensure 'elara-attachments' bucket is created in Supabase Dashboard -> Storage.
-- Alternatively, 'facilities-attachments' bucket can also be shared.
