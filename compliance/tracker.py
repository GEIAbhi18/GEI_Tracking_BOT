"""
Compliance Module — Duplicate Prevention & Audit Tracker
=========================================================
Prevents duplicate WhatsApp notifications for the same compliance item on the same day.
Tracks all reminder dispatches and delivery statuses.

Persistence Strategy:
  1. Primary: Supabase table 'compliance_reminders_log'
  2. Resilient Fallback: Local SQLite database 'data/compliance_reminders.db'
Ensures zero duplicate reminders even if external database connections experience downtime.
"""

import json
import logging
import os
import sqlite3
from datetime import date, datetime
from typing import Any, Dict, Optional

from db import supabase

logger = logging.getLogger(__name__)

SQLITE_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SQLITE_DB_PATH = os.path.join(SQLITE_DB_DIR, "compliance_reminders.db")


def _init_sqlite_db():
    """Ensure local SQLite table exists for offline/fallback deduplication."""
    try:
        os.makedirs(SQLITE_DB_DIR, exist_ok=True)
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compliance_reminders_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    compliance_id TEXT NOT NULL,
                    building TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    sent_date TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    recipient_phone TEXT NOT NULL,
                    whatsapp_status TEXT,
                    delivery_status TEXT,
                    error TEXT,
                    metadata TEXT
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sqlite_compliance_dedup 
                ON compliance_reminders_log (compliance_id, building, due_date, sent_date)
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing local SQLite compliance tracker: {e}")


# Initialize SQLite on module load
_init_sqlite_db()


def has_reminder_been_sent_today(
    compliance_id: str,
    building: str,
    due_date: date,
    check_date: Optional[date] = None,
) -> bool:
    """
    Check if a successful reminder has already been sent for this item today.
    Key: Compliance ID + Building + Due Date + Sent Date.
    """
    c_id = str(compliance_id).strip().upper()
    bld = str(building).strip().upper()
    due_str = due_date.isoformat() if isinstance(due_date, (date, datetime)) else str(due_date)
    today_str = (check_date or date.today()).isoformat()

    # 1. Check Supabase first
    try:
        res = (
            supabase.table("compliance_reminders_log")
            .select("id, whatsapp_status, delivery_status")
            .eq("compliance_id", c_id)
            .eq("building", bld)
            .eq("due_date", due_str)
            .eq("sent_date", today_str)
            .execute()
        )
        if res.data:
            # Check if at least one was accepted/sent successfully
            for row in res.data:
                if row.get("whatsapp_status") in ("accepted", "sent", "delivered"):
                    logger.info(f"Duplicate prevented (Supabase): {c_id} ({bld}) already notified on {today_str}.")
                    return True
    except Exception as sb_err:
        logger.debug(f"Supabase dedup check fallback to SQLite: {sb_err}")

    # 2. Check Local SQLite fallback
    try:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, whatsapp_status FROM compliance_reminders_log 
                WHERE UPPER(compliance_id) = ? 
                  AND UPPER(building) = ? 
                  AND due_date = ? 
                  AND sent_date = ?
            """, (c_id, bld, due_str, today_str))
            rows = cursor.fetchall()
            for r in rows:
                if r[1] in ("accepted", "sent", "delivered"):
                    logger.info(f"Duplicate prevented (SQLite): {c_id} ({bld}) already notified on {today_str}.")
                    return True
    except Exception as sql_err:
        logger.error(f"Error querying SQLite dedup tracker: {sql_err}")

    return False


def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj)


def _sanitize_meta_dict(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _sanitize_meta_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_sanitize_meta_dict(x) for x in d]
    if isinstance(d, (date, datetime)):
        return d.isoformat()
    return d


def log_reminder_attempt(
    compliance_id: str,
    building: str,
    due_date: date,
    recipient_phone: str,
    whatsapp_status: str,
    delivery_status: str,
    sent_date: Optional[date] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Log a compliance reminder dispatch outcome in Supabase and SQLite.
    """
    c_id = str(compliance_id).strip().upper()
    bld = str(building).strip().upper()
    due_str = due_date.isoformat() if isinstance(due_date, (date, datetime)) else str(due_date)
    today = sent_date or date.today()
    today_str = today.isoformat()
    now_iso = datetime.utcnow().isoformat()
    clean_meta = _sanitize_meta_dict(metadata or {})
    meta_json = json.dumps(clean_meta, default=_json_serial)

    # 1. Log to SQLite (ensures immediate local persistence)
    try:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO compliance_reminders_log 
                (compliance_id, building, due_date, sent_date, sent_at, recipient_phone, whatsapp_status, delivery_status, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c_id, bld, due_str, today_str, now_iso, recipient_phone, whatsapp_status, delivery_status, error or "", meta_json))
            conn.commit()
    except Exception as sql_err:
        logger.error(f"Failed to log compliance reminder in SQLite: {sql_err}")

    # 2. Log to Supabase
    try:
        supabase.table("compliance_reminders_log").insert({
            "compliance_id": c_id,
            "building": bld,
            "due_date": due_str,
            "sent_date": today_str,
            "recipient_phone": recipient_phone,
            "whatsapp_status": whatsapp_status,
            "delivery_status": delivery_status,
            "error": error or None,
            "metadata": clean_meta,
        }).execute()
        logger.info(f"Logged compliance reminder in Supabase: {c_id} ({bld}) status={whatsapp_status}")
    except Exception as sb_err:
        logger.debug(f"Could not log compliance reminder in Supabase (may need migration 10): {sb_err}")

    return True

