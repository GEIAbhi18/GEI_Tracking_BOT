-- ==============================================================================
-- 1. Create ENUM Types
-- ==============================================================================
CREATE TYPE user_role AS ENUM ('Guest', 'Client', 'Employee', 'Director', 'Developer');
CREATE TYPE task_type_enum AS ENUM ('TEAM', 'PERSONAL');
CREATE TYPE task_status_enum AS ENUM ('Pending', 'Accepted', 'In Progress', 'Completed', 'Closed', 'Reopened');
CREATE TYPE task_priority_enum AS ENUM ('Critical', 'High', 'Medium', 'Low');

-- ==============================================================================
-- 2. Create Dynamic Teams Table
-- ==============================================================================
CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Seed Initial Teams
INSERT INTO teams (name) VALUES 
('Tech'), 
('Facilities'), 
('Project') 
ON CONFLICT (name) DO NOTHING;

-- ==============================================================================
-- 3. Alter Existing Users Table (Role Update)
-- ==============================================================================
-- Drop the existing CHECK constraint on the role column. 
-- Note: Postgres typically names this `users_role_check` by default.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;

-- Convert existing roles to Title Case to match the new ENUM, then cast
UPDATE users SET role = 'Employee' WHERE role = 'employee';
UPDATE users SET role = 'Director' WHERE role = 'director';

ALTER TABLE users 
    ALTER COLUMN role TYPE user_role 
    USING role::text::user_role;

-- ==============================================================================
-- 4. Alter Existing Tasks Table
-- ==============================================================================
-- Rename existing name to title
ALTER TABLE tasks RENAME COLUMN name TO title;

-- Add new columns
ALTER TABLE tasks
    ADD COLUMN description TEXT,
    ADD COLUMN priority task_priority_enum DEFAULT 'Medium',
    ADD COLUMN due_date DATE,
    ADD COLUMN due_time TIME WITHOUT TIME ZONE,
    ADD COLUMN notes TEXT,
    ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN closed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL,
    ADD COLUMN task_type task_type_enum DEFAULT 'PERSONAL',
    ADD COLUMN parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN closed_at TIMESTAMP WITH TIME ZONE;

-- Migrate existing status to ENUM
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ALTER COLUMN status DROP DEFAULT;

UPDATE tasks SET status = 'Pending' WHERE status = 'pending';
UPDATE tasks SET status = 'In Progress' WHERE status = 'in_progress';
UPDATE tasks SET status = 'Completed' WHERE status = 'completed';

ALTER TABLE tasks 
    ALTER COLUMN status TYPE task_status_enum 
    USING status::text::task_status_enum;

ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'Pending'::task_status_enum;

-- ==============================================================================
-- 5. Indexes for Performance
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_team_id ON tasks(team_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent_id ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

-- ==============================================================================
-- 6. Audit Tables
-- ==============================================================================
CREATE TABLE IF NOT EXISTS tasks_audit (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    old_status task_status_enum,
    new_status task_status_enum,
    changes JSONB,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_audit_task_id ON tasks_audit(task_id);

-- ==============================================================================
-- 7. Triggers
-- ==============================================================================

-- A. Auto-update `updated_at` on tasks
CREATE OR REPLACE FUNCTION update_tasks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tasks_updated_at
BEFORE UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION update_tasks_updated_at();

-- B. Audit Log Trigger for Tasks
CREATE OR REPLACE FUNCTION audit_tasks_changes()
RETURNS TRIGGER AS $$
DECLARE
    changed_data JSONB := '{}'::jsonb;
BEGIN
    -- Capture priority changes
    IF OLD.priority IS DISTINCT FROM NEW.priority THEN
        changed_data := jsonb_set(changed_data, '{priority}', jsonb_build_object('old', OLD.priority, 'new', NEW.priority));
    END IF;
    
    -- Capture assignment changes
    IF OLD.assigned_to IS DISTINCT FROM NEW.assigned_to THEN
        changed_data := jsonb_set(changed_data, '{assigned_to}', jsonb_build_object('old', OLD.assigned_to, 'new', NEW.assigned_to));
    END IF;

    IF OLD.status IS DISTINCT FROM NEW.status OR changed_data != '{}'::jsonb THEN
        INSERT INTO tasks_audit (task_id, changed_by, old_status, new_status, changes)
        VALUES (
            NEW.id,
            NEW.updated_by,
            OLD.status,
            NEW.status,
            changed_data
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_tasks
AFTER UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION audit_tasks_changes();

-- C. Auto-set closed_at when status becomes Closed or Completed
CREATE OR REPLACE FUNCTION handle_task_closure()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('Closed', 'Completed') AND OLD.status NOT IN ('Closed', 'Completed') THEN
        NEW.closed_at = CURRENT_TIMESTAMP;
    ELSIF NEW.status NOT IN ('Closed', 'Completed') THEN
        NEW.closed_at = NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_task_closure
BEFORE UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION handle_task_closure();
