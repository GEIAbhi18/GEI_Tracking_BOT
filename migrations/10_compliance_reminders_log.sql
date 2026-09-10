-- ============================================================
-- Migration 10: Compliance Reminders Log
-- Tracks daily compliance reminder notifications sent to Anoop
-- Ensures deduplication per (compliance_id, building, due_date, sent_date)
-- ============================================================

CREATE TABLE IF NOT EXISTS compliance_reminders_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compliance_id TEXT NOT NULL,
    building TEXT NOT NULL,
    due_date DATE NOT NULL,
    sent_date DATE NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    recipient_phone TEXT NOT NULL,
    whatsapp_status TEXT,
    delivery_status TEXT,
    error TEXT,
    metadata JSONB
);

-- Compound index for rapid deduplication queries
CREATE INDEX IF NOT EXISTS idx_compliance_dedup 
    ON compliance_reminders_log (compliance_id, building, due_date, sent_date);

CREATE INDEX IF NOT EXISTS idx_compliance_sent_date 
    ON compliance_reminders_log (sent_date);
