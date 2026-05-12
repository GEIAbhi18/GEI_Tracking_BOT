-- Migration: Add last_voice_action JSONB column to wa_task_states
-- Purpose: Stores the previous task state for UNDO capability on voice note updates
-- Format: {"task_id": "uuid", "prev_progress": int, "update_id": "uuid", "timestamp": "iso"}
-- The UNDO window is 5 minutes (enforced in application code)

ALTER TABLE wa_task_states
ADD COLUMN IF NOT EXISTS last_voice_action JSONB;

COMMENT ON COLUMN wa_task_states.last_voice_action IS
    'Stores the pre-update snapshot for voice note UNDO. JSON: {task_id, prev_progress, update_id, timestamp}. Expires after 5 minutes (app-enforced).';
