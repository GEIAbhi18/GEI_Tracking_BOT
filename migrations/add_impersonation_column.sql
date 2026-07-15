-- ============================================================
-- Migration: Add impersonation support for System Admin
-- Run this ONCE in Supabase SQL Editor
-- ============================================================

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS impersonating_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
