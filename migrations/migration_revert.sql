-- Drop triggers
DROP TRIGGER IF EXISTS trg_task_closure ON tasks;
DROP FUNCTION IF EXISTS handle_task_closure();
DROP TRIGGER IF EXISTS trg_audit_tasks ON tasks;
DROP FUNCTION IF EXISTS audit_tasks_changes();
DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;
DROP FUNCTION IF EXISTS update_tasks_updated_at();

-- Drop audit table
DROP TABLE IF EXISTS tasks_audit;

-- Revert tasks table changes
ALTER TABLE tasks RENAME COLUMN title TO name;
ALTER TABLE tasks 
    DROP COLUMN IF EXISTS description,
    DROP COLUMN IF EXISTS priority,
    DROP COLUMN IF EXISTS due_date,
    DROP COLUMN IF EXISTS due_time,
    DROP COLUMN IF EXISTS notes,
    DROP COLUMN IF EXISTS created_by,
    DROP COLUMN IF EXISTS updated_by,
    DROP COLUMN IF EXISTS closed_by,
    DROP COLUMN IF EXISTS team_id,
    DROP COLUMN IF EXISTS task_type,
    DROP COLUMN IF EXISTS parent_task_id,
    DROP COLUMN IF EXISTS updated_at,
    DROP COLUMN IF EXISTS closed_at;

-- Revert Tasks Status to VARCHAR
ALTER TABLE tasks ALTER COLUMN status TYPE VARCHAR(20) USING status::text;
UPDATE tasks SET status = 'pending' WHERE status = 'Pending';
UPDATE tasks SET status = 'in_progress' WHERE status = 'In Progress';
UPDATE tasks SET status = 'completed' WHERE status = 'Completed';
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN ('pending', 'in_progress', 'completed'));

-- Drop dynamic teams
DROP TABLE IF EXISTS teams;

-- Revert Users Role to VARCHAR
ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(20) USING role::text;
UPDATE users SET role = 'employee' WHERE role = 'Employee';
UPDATE users SET role = 'director' WHERE role = 'Director';
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('employee', 'director'));

-- Drop ENUMs
DROP TYPE IF EXISTS task_priority_enum;
DROP TYPE IF EXISTS task_status_enum;
DROP TYPE IF EXISTS task_type_enum;
DROP TYPE IF EXISTS user_role;
