-- Migration: Add metadata JSONB column to wa_task_states
-- Purpose: Stores additional context for multi-step flows (e.g. image proof URL during task completion)
-- Format: {"image_url": "https://...", "comment": "..."}

ALTER TABLE wa_task_states
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN wa_task_states.metadata IS
    'Stores additional flow context as JSON. E.g. {"image_url": "..."} during task completion proof upload.';
