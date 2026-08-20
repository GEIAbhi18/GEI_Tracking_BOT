"""
Facilities Module — Configuration
===================================
All env vars, column mappings, building constants, and valid status/type
values for the Facilities department's Google Sheets integration.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google Sheets ────────────────────────────────────────────────────────────
# Spreadsheet ID for Facilities_Master_Tracker_Final
FACILITIES_SHEET_ID = os.getenv("FACILITIES_SHEET_ID", "")

# Reuse the same service account credentials as the feedback module
# (same GCP project — the service account just needs Editor access on the sheet)
FACILITIES_SA_EMAIL = (
    os.getenv("FACILITIES_SA_EMAIL") or
    os.getenv("FACILITIES_SERVICE_ACCOUNT_EMAIL") or
    os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
)
FACILITIES_SA_PRIVATE_KEY = (
    os.getenv("FACILITIES_SA_PRIVATE_KEY") or
    os.getenv("GOOGLE_PRIVATE_KEY") or
    os.getenv("FACILITIES_PRIVATE_KEY", "")
)

# ── Polling ──────────────────────────────────────────────────────────────────
# How often (seconds) the sync engine polls the Sheet for external edits
FACILITIES_POLL_INTERVAL = int(os.getenv("FACILITIES_POLL_INTERVAL", "75"))

# Max retries for failed sync_queue items before giving up
FACILITIES_MAX_RETRIES = int(os.getenv("FACILITIES_MAX_RETRIES", "5"))

# Conflict detection window: if two sources edit the same field within this
# many seconds, it's flagged as a conflict rather than an overwrite
CONFLICT_WINDOW_SECONDS = int(os.getenv("FACILITIES_CONFLICT_WINDOW", "60"))

# ── Building Tabs ────────────────────────────────────────────────────────────
# Exact tab names on the Google Sheet (must match the sheet exactly)
BUILDING_TABS = ["GEBB1", "GEBB2", "GETT", "Common"]

# For fuzzy matching when users type building names in free text
BUILDING_ALIASES = {
    "gebb1": "GEBB1",
    "gebb 1": "GEBB1",
    "bay 1": "GEBB1",
    "bay1": "GEBB1",
    "good earth business bay 1": "GEBB1",
    "gebb2": "GEBB2",
    "gebb 2": "GEBB2",
    "bay 2": "GEBB2",
    "bay2": "GEBB2",
    "good earth business bay 2": "GEBB2",
    "gett": "GETT",
    "tech tower": "GETT",
    "good earth tech tower": "GETT",
    "common": "Common",
    "common area": "Common",
    "common areas": "Common",
}

# ── Column Mapping ───────────────────────────────────────────────────────────
# Maps the Sheet column letters (A-J) to internal field names
# These match the assumed layout; update if the real sheet differs.
COLUMN_MAP = {
    "A": "ref_no",
    "B": "building",
    "C": "type",
    "D": "issue_action",
    "E": "owner",
    "F": "target_date",
    "G": "status",
    "H": "latest_update",
    "I": "created_date",
    "J": "last_modified_by_at",
}

# Reverse mapping: field name → column letter
FIELD_TO_COLUMN = {v: k for k, v in COLUMN_MAP.items()}

# Column indices (1-based, for gspread)
COLUMN_INDEX = {
    "ref_no": 1,
    "building": 2,
    "type": 3,
    "issue_action": 4,
    "owner": 5,
    "target_date": 6,
    "status": 7,
    "latest_update": 8,
    "created_date": 9,
    "last_modified_by_at": 10,
}

# Fields that are writable from GEI_BOT (read-only fields excluded)
WRITABLE_FIELDS = [
    "type", "issue_action", "owner", "target_date",
    "status", "latest_update",
]

# ── Valid Statuses ───────────────────────────────────────────────────────────
# These must match the _Config sheet's valid status list
VALID_STATUSES = [
    "Open",
    "WIP",
    "Closed",
    "On Hold",
    "Escalated",
]

# Status transitions that are always valid
STATUS_TRANSITIONS = {
    "Open": ["WIP", "Closed", "On Hold", "Escalated"],
    "WIP": ["Closed", "On Hold", "Escalated", "Open"],
    "On Hold": ["Open", "WIP", "Closed", "Escalated"],
    "Escalated": ["Open", "WIP", "Closed", "On Hold"],
    "Closed": ["Open"],  # Reopening requires explicit confirm
}

# ── Valid Task Types ─────────────────────────────────────────────────────────
# These appear as a List Message (4 options) during task creation
VALID_TASK_TYPES = [
    "Electrical",
    "Plumbing",
    "Civil",
    "Housekeeping",
]

# ── RAG Status Mapping ───────────────────────────────────────────────────────
# Used for the status chips in task lists (Screen 02)
RAG_STATUS_MAP = {
    "Open": {"emoji": "🔴", "label": "Open"},
    "WIP": {"emoji": "🟡", "label": "WIP"},
    "Closed": {"emoji": "🟢", "label": "Closed"},
    "On Hold": {"emoji": "⚪", "label": "On Hold"},
    "Escalated": {"emoji": "🔴", "label": "Escalated"},
}

# ── Ref No Format ────────────────────────────────────────────────────────────
REF_NO_SEPARATOR = "-"
REF_NO_PAD_WIDTH = 3  # GEBB1-001, GETT-042

# ── LLM ──────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQCLOUD_API_KEY = os.getenv("GROQCLOUD_API_KEY", os.getenv("GROQ_API_KEY", ""))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
FACILITIES_GROQ_MODEL = os.getenv("FACILITIES_GROQ_MODEL", "groq/compound")
FACILITIES_GEMINI_MODEL = os.getenv("FACILITIES_GEMINI_MODEL", "gemini-2.5-flash")

# ── Supabase Storage ─────────────────────────────────────────────────────────
ATTACHMENTS_BUCKET = "facilities-attachments"
MAX_ATTACHMENT_SIZE_MB = 10
