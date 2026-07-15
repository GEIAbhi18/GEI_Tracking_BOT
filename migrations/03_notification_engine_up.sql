-- ==============================================================================
-- Migration: 03_notification_engine_up.sql
-- Description: Creates the notification queue table and associated types
-- ==============================================================================

-- 1. Create Enums for Notification Engine
CREATE TYPE notification_event_enum AS ENUM (
    'Assigned', 
    'Accepted', 
    'Started', 
    'Reminder', 
    'Overdue', 
    'Completed', 
    'Closed', 
    'Follow-up Created'
);

CREATE TYPE notification_status_enum AS ENUM (
    'Pending',
    'Sent',
    'Failed'
);

-- 2. Create the Notifications Queue Table
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    event_type notification_event_enum NOT NULL,
    message TEXT NOT NULL,
    status notification_status_enum DEFAULT 'Pending',
    retry_count INT DEFAULT 0,
    scheduled_for TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Indexes for Notification Polling and querying
CREATE INDEX IF NOT EXISTS idx_notifications_status_scheduled ON notifications(status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_task_id ON notifications(task_id);

-- 4. Trigger to auto-update `updated_at`
CREATE OR REPLACE FUNCTION update_notifications_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_notifications_updated_at
BEFORE UPDATE ON notifications
FOR EACH ROW
EXECUTE FUNCTION update_notifications_updated_at();
