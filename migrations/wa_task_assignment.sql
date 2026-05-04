-- ============================================================
-- Migration: WhatsApp Task Assignment Feature
-- Run this ONCE in Supabase SQL Editor
-- ============================================================

-- 1. Add whatsapp_number to users table
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS whatsapp_number TEXT;

-- 2. Add assigned_by (creator) to tasks table
ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS assigned_by UUID REFERENCES users(id) ON DELETE SET NULL;

-- 3. Add assignment_status column with all required statuses
--    We do NOT touch the existing status column (used by the bot for task progress).
--    assignment_status tracks Kanav→Asif approval flow only.
ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS assignment_status TEXT
  CHECK (assignment_status IN (
    'pending_acceptance',
    'accepted',
    'rejected_pending_reason',
    'rejected',
    'awaiting_new_date'
  ));

-- 4. Add rejection_reason column
ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- 4b. Add accepted_by column (who accepted the task assignment)
ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS accepted_by UUID REFERENCES users(id) ON DELETE SET NULL;

-- 5. Create wa_task_states table for persistent WhatsApp conversation state
--    (In-memory state is lost on Render restarts; this keeps flows alive)
CREATE TABLE IF NOT EXISTS wa_task_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_number TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Seed whatsapp_number values for existing users
--    ⚠️  UPDATE THESE with real phone numbers in E.164 format (e.g. 919812345678)
--    Format: country_code + number, no + prefix, no spaces
UPDATE users SET whatsapp_number = '918700057759' WHERE name = 'Asif';
UPDATE users SET whatsapp_number = '919811867829' WHERE name = 'Kanav';

-- 7. Index for fast lookup by whatsapp_number
CREATE INDEX IF NOT EXISTS idx_users_whatsapp ON users(whatsapp_number);
CREATE INDEX IF NOT EXISTS idx_wa_states_number ON wa_task_states(whatsapp_number);
