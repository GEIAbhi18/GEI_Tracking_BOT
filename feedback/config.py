"""
Feedback Bot Configuration
==========================
Centralized constants, env vars, and configuration for the feedback module.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google Sheets Credentials (env-var based — no JSON file needed) ──────────
GOOGLE_SERVICE_ACCOUNT_EMAIL = os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
GOOGLE_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY", "").replace("\\n", "\n")

# Google Spreadsheet ID (the long string in the sheet URL)
FEEDBACK_SHEET_ID = os.getenv("FEEDBACK_SHEET_ID", "")

# ── Sheet Names ──────────────────────────────────────────────────────────────
MASTER_SHEET_NAME = os.getenv("FEEDBACK_MASTER_SHEET", "MASTER")
ESCALATIONS_SHEET_NAME = os.getenv("FEEDBACK_ESCALATIONS_SHEET", "ESCALATIONS")
PENDING_FEEDBACK_SHEET_NAME = os.getenv("FEEDBACK_PENDING_SHEET", "Pending Feedback")

# Building-specific sheets
BUILDING_SHEETS = {
    "GEBB1": os.getenv("FEEDBACK_SHEET_GEBB1", "GEBB1"),
    "GEBB2": os.getenv("FEEDBACK_SHEET_GEBB2", "GEBB2"),
    "GETT": os.getenv("FEEDBACK_SHEET_GETT", "GETT"),
}

# ── Feedback Bot API Key ─────────────────────────────────────────────────────
FEEDBACK_API_KEY = os.getenv("FEEDBACK_API_KEY", "")

# ── WhatsApp Config (reuse from main bot) ────────────────────────────────────
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

# ── WhatsApp Flow Config (NEW) ──────────────────────────────────────────────
WHATSAPP_FLOW_ID = os.getenv("WHATSAPP_FLOW_ID", "")
WHATSAPP_FLOW_TEMPLATE_NAME = os.getenv("WHATSAPP_FLOW_TEMPLATE_NAME", "gei_feedback_request")

# ── Reminder Timing ─────────────────────────────────────────────────────────
REMINDER_INTERVAL_HOURS = int(os.getenv("REMINDER_INTERVAL_HOURS", "6"))
MAX_REMINDERS = int(os.getenv("MAX_REMINDERS", "2"))

# Legacy env vars (still supported for backward compat)
REMINDER_1_DELAY_SECONDS = int(os.getenv("FEEDBACK_REMINDER_1_DELAY", str(REMINDER_INTERVAL_HOURS * 3600)))
REMINDER_2_DELAY_SECONDS = int(os.getenv("FEEDBACK_REMINDER_2_DELAY", str(REMINDER_INTERVAL_HOURS * 2 * 3600)))

# ── Escalation Keywords ─────────────────────────────────────────────────────
NEGATIVE_KEYWORDS = [
    "delay", "poor", "unresolved", "rude", "dissatisfied", "bad", "slow",
    "late", "not resolved", "issue persists", "worst", "terrible", "never",
    "pathetic", "ignored", "useless", "horrible", "no response",
    "not fixed", "still broken", "disgusting",
]

# ── Feedback Flow Stages ─────────────────────────────────────────────────────
# WhatsApp Flows: only two active stages (template sent → done)
STAGE_FLOW_SENT = "flow_sent"
STAGE_DONE = "done"

# Legacy stages (kept for backward compat during migration)
STAGE_AWAITING_START = "awaiting_start"
STAGE_Q1 = "q1"
STAGE_Q2 = "q2"
STAGE_Q3 = "q3"
STAGE_Q4 = "q4"

# ── Valid Score Values ───────────────────────────────────────────────────────
VALID_SCORES = {"1", "2", "3", "4", "5"}

# ── Max Invalid Attempts (legacy — not used with Flows) ─────────────────────
MAX_INVALID_ATTEMPTS = 3

# ── Cron Interval for Reminder Check (seconds) ──────────────────────────────
REMINDER_CRON_INTERVAL = int(os.getenv("FEEDBACK_REMINDER_CRON_INTERVAL", "900"))  # 15 min
