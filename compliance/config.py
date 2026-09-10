"""
Compliance Module — Configuration
==================================
Configuration settings, building mappings, column structures, and credentials
for the independent Compliance Management reminder module.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google Drive / Sheet Configuration ───────────────────────────────────────
# Default Compliance Management Google Sheet / Drive File ID
COMPLIANCE_SHEET_ID = os.getenv(
    "COMPLIANCE_SHEET_ID",
    "1o2c4ogp56YNbPA4xufINDsD8AUuaX-BK"
)

# Service Account credentials (reusing existing Facilities configuration)
COMPLIANCE_SA_EMAIL = (
    os.getenv("FACILITIES_SERVICE_ACCOUNT_EMAIL")
    or os.getenv("FACILITIES_SA_EMAIL")
    or os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
)

COMPLIANCE_SA_PRIVATE_KEY = (
    os.getenv("FACILITIES_SERVICE_ACCOUNT_PRIVATE_KEY")
    or os.getenv("FACILITIES_SA_PRIVATE_KEY")
    or os.getenv("FACILITIES_PRIVATE_KEY")
    or os.getenv("GOOGLE_PRIVATE_KEY", "")
)

# ── Building & Sheet Tabs ───────────────────────────────────────────────────
# Monitored building tabs in the sheet (Management Dashboard is intentionally excluded)
COMPLIANCE_BUILDING_TABS = ["GEBB1", "GEBB2", "GETT"]

# Building display mapping
BUILDING_NAME_MAPPING = {
    "GEBB1": "Bay 1",
    "GEBB2": "Bay 2",
    "GETT": "Trade Tower",
}

# ── WhatsApp / Meta Configuration ───────────────────────────────────────────
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
WA_API_BASE = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}" if PHONE_NUMBER_ID else ""

# Meta Approved Utility Template Name & Language
COMPLIANCE_TEMPLATE_NAME = "compliance_due_reminder"
COMPLIANCE_TEMPLATE_LANG = "en"

# Recipient: Only Anoop Sir receives compliance reminders
DEFAULT_ANOOP_PHONE = "919211501013"
ANOOP_WHATSAPP_NUMBER = os.getenv("ANOOP_WHATSAPP_NUMBER", DEFAULT_ANOOP_PHONE)

# ── Scheduling & Timezone ────────────────────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
COMPLIANCE_CHECK_HOUR = int(os.getenv("COMPLIANCE_CHECK_HOUR", "9"))
COMPLIANCE_CHECK_MINUTE = int(os.getenv("COMPLIANCE_CHECK_MINUTE", "0"))

# ── Sheet Layout Definition ─────────────────────────────────────────────────
HEADER_ROW_INDEX = 4  # 1-indexed row containing table column headers
DATA_START_ROW_INDEX = 5

# Canonical column indices in openpyxl (1-indexed)
COL_ID = 1
COL_CONTROL_GROUP = 2
COL_CATEGORY = 3
COL_REQUIREMENT = 4
COL_APPLICABILITY = 8
COL_ISSUE_DATE = 9
COL_DUE_DATE = 10
COL_STATUS = 11
COL_EVIDENCE = 12
COL_REMARKS = 13
COL_OWNER = 14
