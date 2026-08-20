-- ==============================================================================
-- Migration 07: Facilities Module — Google Sheets Two-Way Sync
-- ==============================================================================
-- Creates: facilities_sessions, building_counters, sync_queue, conflicts,
--          facilities_audit_log, row_cache, facilities_attachments
-- Alters:  users (adds department, permitted_buildings columns)
-- Seeds:   building_counters for GEBB1, GEBB2, GETT, Common
--          permitted_buildings for existing Facilities users
-- ==============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend users table with Facilities-specific columns
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS permitted_buildings TEXT[] DEFAULT '{}';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Facilities Sessions — conversation state for multi-step flows
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facilities_sessions (
    whatsapp_number TEXT PRIMARY KEY,
    current_flow_state TEXT,
    draft_task_json JSONB DEFAULT '{}',
    context_json JSONB DEFAULT '{}',
    last_active_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_facilities_sessions_state
    ON facilities_sessions(current_flow_state);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Building Counters — atomic Ref No generation with row-level locking
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS building_counters (
    building TEXT PRIMARY KEY,
    next_ref_no INT NOT NULL DEFAULT 1
);

-- Seed counters for the 4 building groups
INSERT INTO building_counters (building, next_ref_no) VALUES
    ('GEBB1', 1),
    ('GEBB2', 1),
    ('GETT', 1),
    ('Common', 1)
ON CONFLICT (building) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Atomic Ref No generation function (uses FOR UPDATE row lock)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION generate_ref_no(p_building TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_next INT;
    v_ref TEXT;
BEGIN
    -- Row-level lock prevents concurrent collision
    UPDATE building_counters
    SET next_ref_no = next_ref_no + 1
    WHERE building = p_building
    RETURNING next_ref_no - 1 INTO v_next;

    IF v_next IS NULL THEN
        RAISE EXCEPTION 'Unknown building: %', p_building;
    END IF;

    -- Format: GEBB1-001, GETT-042, etc.
    v_ref := p_building || '-' || LPAD(v_next::TEXT, 3, '0');
    RETURN v_ref;
END;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Sync Queue — tracks pending/completed writes to Google Sheets
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_no TEXT NOT NULL,
    building TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    attempted_value TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed')),
    idempotency_key TEXT UNIQUE NOT NULL,
    retry_count INT DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    synced_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status);
CREATE INDEX IF NOT EXISTS idx_sync_queue_ref_no ON sync_queue(ref_no);
CREATE INDEX IF NOT EXISTS idx_sync_queue_created ON sync_queue(created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Conflicts — when GEI_BOT and Sheet edits collide on the same field
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_no TEXT NOT NULL,
    field TEXT NOT NULL,
    gei_bot_value TEXT,
    gei_bot_ts TIMESTAMPTZ,
    sheet_value TEXT,
    sheet_ts TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved')),
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status);
CREATE INDEX IF NOT EXISTS idx_conflicts_ref_no ON conflicts(ref_no);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Facilities Audit Log — full history for Screen 19 + digest
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facilities_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_no TEXT NOT NULL,
    source TEXT NOT NULL
        CHECK (source IN ('gei_bot', 'google_sheets', 'system')),
    actor TEXT,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fac_audit_ref_no ON facilities_audit_log(ref_no);
CREATE INDEX IF NOT EXISTS idx_fac_audit_timestamp ON facilities_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_fac_audit_source ON facilities_audit_log(source);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Row Cache — local mirror of Sheet data for fast reads + diffing
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS row_cache (
    ref_no TEXT PRIMARY KEY,
    building TEXT NOT NULL,
    type TEXT,
    issue_action TEXT,
    owner TEXT,
    target_date TEXT,
    status TEXT,
    latest_update TEXT,
    created_date TEXT,
    last_modified_by_at TEXT,
    last_synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_row_cache_building ON row_cache(building);
CREATE INDEX IF NOT EXISTS idx_row_cache_owner ON row_cache(owner);
CREATE INDEX IF NOT EXISTS idx_row_cache_status ON row_cache(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Facilities Attachments — files stored in Supabase Storage
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facilities_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_no TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_name TEXT,
    file_type TEXT,
    uploaded_by TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fac_attachments_ref_no
    ON facilities_attachments(ref_no);

-- ─────────────────────────────────────────────────────────────────────────────
-- 10. Seed permitted_buildings from existing building_users mappings
-- ─────────────────────────────────────────────────────────────────────────────
-- Set department = 'Facilities' for users who are mapped to buildings
UPDATE users
SET department = 'Facilities'
WHERE id IN (
    SELECT DISTINCT user_id FROM building_users
);

-- Populate permitted_buildings from the building_users mapping table
-- This converts the many-to-many mapping into an array on the users table
UPDATE users u
SET permitted_buildings = sub.buildings
FROM (
    SELECT bu.user_id,
           ARRAY_AGG(b.name ORDER BY b.name) AS buildings
    FROM building_users bu
    JOIN buildings b ON b.id = bu.building_id
    GROUP BY bu.user_id
) sub
WHERE u.id = sub.user_id;

-- ─────────────────────────────────────────────────────────────────────────────
-- 11. Create Supabase Storage bucket for Facilities attachments
-- ─────────────────────────────────────────────────────────────────────────────
-- NOTE: Storage buckets are created via Supabase Dashboard or API, not SQL.
-- You must manually create a bucket named 'facilities-attachments' in the
-- Supabase Dashboard → Storage → New Bucket, with these settings:
--   - Name: facilities-attachments
--   - Public: false (private — accessed via signed URLs)
--   - File size limit: 10MB
--   - Allowed MIME types: image/jpeg, image/png, application/pdf
