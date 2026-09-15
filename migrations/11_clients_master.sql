-- Migration 11: Create clients table for Factech Client Automation & Identification
-- Master data synchronized from Google Sheets (MASTER tab)

CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    building TEXT,
    company_name TEXT NOT NULL,
    floor TEXT,
    unit_number TEXT,
    admin_name TEXT,
    designation TEXT,
    mobile_number TEXT NOT NULL,
    email TEXT,
    factech_client_id TEXT,
    is_active BOOLEAN DEFAULT true,
    source_sheet TEXT DEFAULT 'MASTER',
    sync_key TEXT UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Performance and lookup indexes
CREATE INDEX IF NOT EXISTS idx_clients_mobile_number ON clients(mobile_number);
CREATE INDEX IF NOT EXISTS idx_clients_building ON clients(building);
CREATE INDEX IF NOT EXISTS idx_clients_unit_number ON clients(unit_number);
CREATE INDEX IF NOT EXISTS idx_clients_sync_key ON clients(sync_key);
CREATE INDEX IF NOT EXISTS idx_clients_factech_client_id ON clients(factech_client_id);
CREATE INDEX IF NOT EXISTS idx_clients_is_active ON clients(is_active);
