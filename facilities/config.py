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
FACILITIES_API_KEY = os.getenv("FACILITIES_API_KEY", "")

# Service Account credentials for Facilities module
_fac_sa_email = (
    os.getenv("FACILITIES_SERVICE_ACCOUNT_EMAIL") or
    os.getenv("FACILITIES_SA_EMAIL")
)
_fac_sa_key = (
    os.getenv("FACILITIES_SERVICE_ACCOUNT_PRIVATE_KEY") or
    os.getenv("FACILITIES_SA_PRIVATE_KEY") or
    os.getenv("FACILITIES_PRIVATE_KEY")
)

if _fac_sa_email:
    FACILITIES_SA_EMAIL = _fac_sa_email
    # Use dedicated key if provided, else fall back to GOOGLE_PRIVATE_KEY
    FACILITIES_SA_PRIVATE_KEY = _fac_sa_key or os.getenv("GOOGLE_PRIVATE_KEY", "")
else:
    FACILITIES_SA_EMAIL = os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
    FACILITIES_SA_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY", "")

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
# Maps the Sheet column letters to internal field names.
#
# GEBB1, GEBB2, Common layout (10 columns A-J):
#   A: Ref. No.   B: Type   C: Key Issue / Action   D: Latest Update
#   E: Added by   F: Owner  G: Date Raised          H: Target Date
#   I: Delay Days J: Status
#
# GETT layout (9 columns A-I — no "Added by" column):
#   A: Ref. No.   B: Type   C: Key Issue / Action   D: Latest Update
#   E: Owner      F: Date Raised   G: Target Date   H: Delay Days
#   I: Status
#
# NOTE: "building" is derived from the tab name, not a column.
# "created_date" stores Date Raised and "last_modified_by_at" stores Added by.

# Default column map (GEBB1, GEBB2, Common)
COLUMN_MAP = {
    "A": "ref_no",
    "B": "type",
    "C": "issue_action",
    "D": "latest_update",
    "E": "last_modified_by_at",   # "Added by" on the sheet
    "F": "owner",
    "G": "created_date",          # "Date Raised" on the sheet
    "H": "target_date",
    "I": "delay_days",            # computed field — not stored in row_cache
    "J": "status",
}

# GETT has a different layout (no "Added by" column)
COLUMN_MAP_GETT = {
    "A": "ref_no",
    "B": "type",
    "C": "issue_action",
    "D": "latest_update",
    "E": "owner",                 # GETT has Owner in col E (no Added by)
    "F": "created_date",          # "Date Raised"
    "G": "target_date",
    "H": "delay_days",
    "I": "status",
}

def get_column_map(building: str) -> dict:
    """Get the column map for a specific building tab."""
    if building == "GETT":
        return COLUMN_MAP_GETT
    return COLUMN_MAP

# Reverse mapping: field name → column letter (default layout)
FIELD_TO_COLUMN = {v: k for k, v in COLUMN_MAP.items()}

# Column indices (1-based, for gspread) — default layout (GEBB1/GEBB2/Common)
COLUMN_INDEX = {
    "ref_no": 1,
    "type": 2,
    "issue_action": 3,
    "latest_update": 4,
    "last_modified_by_at": 5,   # "Added by"
    "owner": 6,
    "created_date": 7,          # "Date Raised"
    "target_date": 8,
    "delay_days": 9,
    "status": 10,
}

# GETT column indices
COLUMN_INDEX_GETT = {
    "ref_no": 1,
    "type": 2,
    "issue_action": 3,
    "latest_update": 4,
    "owner": 5,
    "created_date": 6,          # "Date Raised"
    "target_date": 7,
    "delay_days": 8,
    "status": 9,
}

def get_column_index(building: str) -> dict:
    """Get the column index mapping for a specific building tab."""
    if building == "GETT":
        return COLUMN_INDEX_GETT
    return COLUMN_INDEX

# Fields that are writable from GEI_BOT (read-only fields excluded)
WRITABLE_FIELDS = [
    "type", "issue_action", "latest_update", "owner",
    "target_date", "status",
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
