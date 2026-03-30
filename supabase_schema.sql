-- 1. Create Users Table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('employee', 'director')),
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_reminder_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Create Projects Table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'completed', 'on_hold')),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Create Tasks Table
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    deadline TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed')),
    planned_start_date TIMESTAMP WITH TIME ZONE,
    planned_end_date TIMESTAMP WITH TIME ZONE,
    actual_start_date TIMESTAMP WITH TIME ZONE,
    actual_end_date TIMESTAMP WITH TIME ZONE,
    attachments TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Create Updates Table (task_updates)
CREATE TABLE IF NOT EXISTS updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    employee_id UUID REFERENCES users(id) ON DELETE SET NULL,
    progress INT NOT NULL CHECK (progress >= 0 AND progress <= 100),
    blockers TEXT,
    note TEXT,
    images TEXT[], 
    rag VARCHAR(5) NOT NULL CHECK (rag IN ('RED', 'AMBER', 'GREEN')),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Create Tickets Table
CREATE TABLE IF NOT EXISTS tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Create Ticket Messages Table
CREATE TABLE IF NOT EXISTS ticket_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    sender_id UUID REFERENCES users(id) ON DELETE SET NULL,
    message_text TEXT NOT NULL,
    image_url TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- SEED DATA
-- Replace with actual Telegram IDs if known, defaults used here for structure
INSERT INTO users (telegram_id, name, role) VALUES 
(123456789, 'Asif', 'employee'),
(987654321, 'Kanav', 'director')
ON CONFLICT (telegram_id) DO NOTHING;

DO $$
DECLARE
    asif_id UUID;
    kanav_id UUID;
    proj1_id UUID;
    proj2_id UUID;
BEGIN
    SELECT id INTO asif_id FROM users WHERE name = 'Asif' LIMIT 1;
    SELECT id INTO kanav_id FROM users WHERE name = 'Kanav' LIMIT 1;

    -- Insert Projects
    INSERT INTO projects (name, created_by) VALUES ('Top Terrace', kanav_id) RETURNING id INTO proj1_id;
    INSERT INTO projects (name, created_by) VALUES ('9TH FLOOR (CENTRIC)', kanav_id) RETURNING id INTO proj2_id;

    -- Insert Tasks for Top Terrace
    INSERT INTO tasks (project_id, assigned_to, name, deadline) VALUES 
    (proj1_id, asif_id, 'Tile, membrane removal + malba shifting + slope checking + corrections', '2026-02-27 23:59:59+00T'),
    (proj1_id, asif_id, 'Solar panel installation', '2026-02-28 23:59:59+00T'),
    (proj1_id, asif_id, 'Waterproofing + ponding test', '2026-03-07 23:59:59+00T');

    -- Insert Tasks for 9TH FLOOR (CENTRIC)
    INSERT INTO tasks (project_id, assigned_to, name, deadline) VALUES 
    (proj2_id, asif_id, 'Tile removal + malba shifting + slope checking + corrections', '2026-02-27 23:59:59+00T'),
    (proj2_id, asif_id, 'Waterproofing + ponding test', '2026-02-28 23:59:59+00T');
END $$;
