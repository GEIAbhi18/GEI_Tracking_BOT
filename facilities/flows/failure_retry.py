"""
Screen 16 — Failure/Retry
===========================
When a Sheets API write fails:
  - "GEI_BOT Updated: ✅ Synced" (local state is updated)
  - "Google Sheets: ⏳ Sync Pending" + auto-retry
  - Push follow-up message once retry succeeds
  - Never a false "Synced" on the Sheets side

Retry logic lives in sync_engine.py. This module provides
message formatting helpers.
"""

import logging

logger = logging.getLogger(__name__)


def format_partial_sync_message(ref_no: str, action: str, field: str = None) -> str:
    """Format a message for when local update succeeded but Sheet sync failed."""
    return (
        f"⚠️ *{action} — {ref_no}*\n\n"
        f"✅ *GEI_BOT:* Updated\n"
        f"⏳ *Google Sheets:* Sync Pending\n\n"
        f"_The update has been saved locally and will be automatically "
        f"synced to Google Sheets. You'll receive a confirmation "
        f"once the sync completes._"
    )


def format_sync_success_followup(ref_no: str, field: str, value: str) -> str:
    """Format the follow-up message when a previously failed sync succeeds."""
    return (
        f"✅ *Sync Update — {ref_no}*\n\n"
        f"*Google Sheets:* ✅ Synced\n\n"
        f"The {field} update has been successfully synced "
        f"to Google Sheets.\n\n"
        f"_No action needed._"
    )
