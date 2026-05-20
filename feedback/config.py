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

# ── Reminder Timing (in seconds) ─────────────────────────────────────────────
REMINDER_1_DELAY_SECONDS = int(os.getenv("FEEDBACK_REMINDER_1_DELAY", str(6 * 3600)))   # 6 hours
REMINDER_2_DELAY_SECONDS = int(os.getenv("FEEDBACK_REMINDER_2_DELAY", str(12 * 3600)))  # 12 hours

# ── Escalation Keywords ─────────────────────────────────────────────────────
NEGATIVE_KEYWORDS = [
    "delay", "poor", "unresolved", "rude", "dissatisfied", "bad", "slow",
    "late", "not resolved", "issue persists", "worst", "terrible", "never",
    "pathetic", "ignored", "useless"
]

# ── Feedback Flow Stages ─────────────────────────────────────────────────────
STAGE_AWAITING_START = "awaiting_start"
STAGE_Q1 = "q1"
STAGE_Q2 = "q2"
STAGE_Q3 = "q3"
STAGE_Q4 = "q4"
STAGE_DONE = "done"

# ── Valid Score Values ───────────────────────────────────────────────────────
VALID_SCORES = {"1", "2", "3", "4", "5"}

# ── Max Invalid Attempts ─────────────────────────────────────────────────────
MAX_INVALID_ATTEMPTS = 3

# ── Cron Interval for Reminder Check (seconds) ──────────────────────────────
REMINDER_CRON_INTERVAL = int(os.getenv("FEEDBACK_REMINDER_CRON_INTERVAL", "300"))  # 5 min
