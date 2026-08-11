-- ==============================================================================
-- Migration 06: Buildings Hierarchy
-- ==============================================================================
-- Creates: buildings, building_users tables
-- Alters: projects (adds building_id)
-- Creates: new users (Anoop, Ritesh, Kuldeep, Gopal)
-- Inserts: building↔user mappings
-- Updates: existing projects with building assignments
-- ==============================================================================

-- 1. Create Buildings Table
CREATE TABLE IF NOT EXISTS buildings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Insert the three buildings
INSERT INTO buildings (name) VALUES ('GETT'), ('GEBB1'), ('GEBB2')
ON CONFLICT (name) DO NOTHING;

-- 3. Create Building↔User mapping table (many-to-many)
CREATE TABLE IF NOT EXISTS building_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id UUID NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(building_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_building_users_user ON building_users(user_id);
CREATE INDEX IF NOT EXISTS idx_building_users_building ON building_users(building_id);

-- 4. Add building_id column to projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS building_id UUID REFERENCES buildings(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_projects_building ON projects(building_id);

-- 5. Create missing users (Anoop, Ritesh, Kuldeep, Gopal)
INSERT INTO users (name, role, whatsapp_number)
VALUES 
    ('Anoop', 'Employee', '919211501013'),
    ('Ritesh', 'Employee', '919991507937'),
    ('Kuldeep', 'Employee', '917838161163'),
    ('Gopal', 'Employee', '917056134619')
ON CONFLICT DO NOTHING;

-- 6. Insert building↔user mappings using subqueries (no hardcoded UUIDs)
-- Vikram → GEBB1, GEBB2
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB1' AND u.name = 'Vikram'
ON CONFLICT (building_id, user_id) DO NOTHING;

INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB2' AND u.name = 'Vikram'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Ritesh → GEBB1
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB1' AND u.name = 'Ritesh'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Kuldeep → GEBB2
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB2' AND u.name = 'Kuldeep'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Vikash → GETT
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GETT' AND u.name = 'Vikash'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Gopal → GETT
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GETT' AND u.name = 'Gopal'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Arjun → GETT, GEBB1, GEBB2
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GETT' AND u.name = 'Arjun'
ON CONFLICT (building_id, user_id) DO NOTHING;

INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB1' AND u.name = 'Arjun'
ON CONFLICT (building_id, user_id) DO NOTHING;

INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB2' AND u.name = 'Arjun'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- Anoop → GETT, GEBB1, GEBB2
INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GETT' AND u.name = 'Anoop'
ON CONFLICT (building_id, user_id) DO NOTHING;

INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB1' AND u.name = 'Anoop'
ON CONFLICT (building_id, user_id) DO NOTHING;

INSERT INTO building_users (building_id, user_id)
SELECT b.id, u.id FROM buildings b, users u WHERE b.name = 'GEBB2' AND u.name = 'Anoop'
ON CONFLICT (building_id, user_id) DO NOTHING;

-- 7. Map existing projects to buildings
-- Bay 1 - top terrace waterproofing → GEBB1
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GEBB1')
WHERE id = 'f20f6399-bfb3-4f43-a414-247cb54cf882';

-- 9th floor waterproofing → GEBB2
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GEBB2')
WHERE id = '2c4b507a-4caa-4054-a2b2-18911d65bb10';

-- Ledor GEBB2 Ground floor → GEBB2
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GEBB2')
WHERE id = 'fcc7b7f1-d13b-4a7f-85d9-4c68dcad48fe';

-- Omnicom 7th & 8th floor → GEBB2
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GEBB2')
WHERE id = 'e9b8e305-f8b9-4b7b-bf3c-59979fc46c89';

-- Green park → GEBB1
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GEBB1')
WHERE id = '3b2f1616-8bc9-420f-9d34-e56d8ae97226';

-- GETT-CHILLER Reimbursement → GETT
UPDATE projects SET building_id = (SELECT id FROM buildings WHERE name = 'GETT')
WHERE id = '5c0ee17e-be87-460c-916e-f9b41ca0b423';

-- 8. Mark removed projects as completed (safer than DELETE — preserves task history)
-- WARNING: If you want to permanently delete, use:
--   DELETE FROM projects WHERE id IN ('f953d739-...', 'ce30f4cb-...', '01b790ee-...');
--   This WILL cascade-delete all tasks and updates for those projects.
UPDATE projects SET status = 'completed' WHERE id IN (
    'f953d739-fd3c-446f-a322-6e6227afabbf',  -- Dummy Test
    'ce30f4cb-7d25-4a49-a0fe-c5ed0a8346b0',  -- GEI_BOT Testing Version 2.0
    '01b790ee-ff75-4cb9-b668-c3c0e3638882'   -- Demo testing
);
