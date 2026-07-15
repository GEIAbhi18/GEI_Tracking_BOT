-- ==============================================================================
-- Phase 8: Personal Task Manager Additions & RLS
-- ==============================================================================

-- 1. Add new columns for Personal Tasks
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS reminder_time TIMESTAMP WITH TIME ZONE;

-- 2. Enable RLS on the tasks table
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;

-- 3. Policy for Team Tasks (Always visible for now, or depending on future team rules)
-- For this phase, we ensure they remain visible to everyone so we don't break existing flows
CREATE POLICY team_tasks_visibility ON tasks 
    FOR ALL
    USING (task_type = 'TEAM' OR task_type IS NULL);

-- 4. Policy for Personal Tasks (Strict Privacy)
-- A personal task can only be viewed/edited by its creator or assignee
CREATE POLICY personal_tasks_privacy ON tasks 
    FOR ALL
    USING (
        task_type = 'PERSONAL' 
        AND (
            created_by = auth.uid() 
            OR assigned_to = auth.uid()
        )
    );

-- Note: In Supabase, if the backend uses the service_role key, these policies 
-- are bypassed. The backend Python code must also strictly enforce these rules.
