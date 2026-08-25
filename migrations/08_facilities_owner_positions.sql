-- ==============================================================================
-- Migration 08: Facilities Owner Position → User Mapping
-- ==============================================================================
-- Creates: facilities_owner_positions
-- Purpose: Central mapping table from Google Sheet "Owner" position titles
--          to actual application users. This is the single source of truth
--          for resolving Owner Position → User → WhatsApp Number.
--
-- The Google Sheet "Owner" column contains POSITION TITLES (e.g.,
-- "Facility Manager GEBB1" or "Facility Manager"), NOT employee names.
-- This table bridges that gap.
-- ==============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Create the Owner Position mapping table
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facilities_owner_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position_title TEXT NOT NULL,
    user_name TEXT NOT NULL,
    building TEXT,  -- NULL for cross-building positions (e.g. Facility Head, Facility Director)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Drop any old single-column unique constraint on position_title if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'facilities_owner_positions_position_title_key'
    ) THEN
        ALTER TABLE facilities_owner_positions DROP CONSTRAINT facilities_owner_positions_position_title_key;
    END IF;
END $$;

-- Create unique index on (position_title, COALESCE(building, ''))
CREATE UNIQUE INDEX IF NOT EXISTS idx_fac_owner_pos_title_bldg
    ON facilities_owner_positions (position_title, COALESCE(building, ''));

CREATE INDEX IF NOT EXISTS idx_fac_owner_pos_user
    ON facilities_owner_positions(user_name);

CREATE INDEX IF NOT EXISTS idx_fac_owner_pos_building
    ON facilities_owner_positions(building);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Seed the mandatory mapping
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO facilities_owner_positions (position_title, user_name, building) VALUES
    ('Facility Head',           'Anoop',       NULL),
    ('Facility Manager GEBB1',  'Vikramjeet',  'GEBB1'),
    ('Facility Manager GEBB2',  'Vikramjeet',  'GEBB2'),
    ('Facility Manager GETT',   'Vikash',      'GETT'),
    ('Facility Director',       'Kanav',       NULL),
    ('Facility Manager',        'Vikramjeet',  'GEBB1'),
    ('Facility Manager',        'Vikramjeet',  'GEBB2'),
    ('Facility Manager',        'Vikash',      'GETT')
ON CONFLICT (position_title, COALESCE(building, '')) DO UPDATE SET
    user_name  = EXCLUDED.user_name,
    building   = EXCLUDED.building,
    updated_at = NOW();
