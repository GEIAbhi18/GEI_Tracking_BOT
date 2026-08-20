"""
Screen 17 — Conflict Resolution UI
=====================================
Both values, both timestamps.
Keep Sheet / Keep GEI_BOT / View Full History → Reply Buttons (3 options).
"""

import logging
from datetime import datetime

from whatsapp.ux import send_text, send_interactive_buttons
from db import supabase
from facilities.sheets_client import resolve_conflict

logger = logging.getLogger(__name__)


def show_conflict(sender: str, conflict_id: str, user: dict):
    """Show the conflict resolution UI (Screen 17)."""
    try:
        res = supabase.table("conflicts").select("*").eq("id", conflict_id).execute()
        if not res.data:
            send_text(sender, "Conflict not found.")
            return

        c = res.data[0]
        ref_no = c.get("ref_no", "—")
        field = c.get("field", "—")

        # Format timestamps
        bot_ts = _format_ts(c.get("gei_bot_ts"))
        sheet_ts = _format_ts(c.get("sheet_ts"))

        msg = (
            f"⚠️ *Conflict Detected — {ref_no}*\n"
            f"{'─' * 25}\n\n"
            f"*Field:* {field}\n\n"
            f"📱 *GEI_BOT value:*\n"
            f"  \"{c.get('gei_bot_value', '—')}\"\n"
            f"  _at {bot_ts}_\n\n"
            f"📊 *Google Sheets value:*\n"
            f"  \"{c.get('sheet_value', '—')}\"\n"
            f"  _at {sheet_ts}_\n\n"
            f"Both sources edited this field within 60 seconds. "
            f"Which value should be kept?"
        )

        buttons = [
            {"id": f"fac_keep_sheet_{conflict_id}", "title": "📊 Keep Sheet"},
            {"id": f"fac_keep_bot_{conflict_id}", "title": "📱 Keep GEI_BOT"},
            {"id": f"fac_conflict_history_{ref_no}", "title": "📜 View History"},
        ]
        send_interactive_buttons(sender, msg, buttons)

    except Exception as e:
        logger.error(f"show_conflict failed: {e}")
        send_text(sender, "Error loading conflict details.")


def resolve_keep_sheet(sender: str, conflict_id: str, user: dict):
    """Resolve conflict by keeping the Sheet value."""
    try:
        result = resolve_conflict(
            conflict_id, "keep_sheet",
            resolved_by=user.get("name", "unknown"),
            keep="keep_sheet",
        )

        send_text(
            sender,
            f"✅ *Conflict Resolved*\n\n"
            f"Kept the *Google Sheets* value: \"{result.get('winning_value', '—')}\"\n\n"
            f"Both GEI_BOT and Google Sheets are now in sync."
        )

    except Exception as e:
        logger.error(f"resolve_keep_sheet failed: {e}")
        send_text(sender, f"Failed to resolve conflict: {e}")


def resolve_keep_bot(sender: str, conflict_id: str, user: dict):
    """Resolve conflict by keeping the GEI_BOT value."""
    try:
        result = resolve_conflict(
            conflict_id, "keep_gei_bot",
            resolved_by=user.get("name", "unknown"),
            keep="keep_gei_bot",
        )

        send_text(
            sender,
            f"✅ *Conflict Resolved*\n\n"
            f"Kept the *GEI_BOT* value: \"{result.get('winning_value', '—')}\"\n\n"
            f"The Google Sheet has been updated to match."
        )

    except Exception as e:
        logger.error(f"resolve_keep_bot failed: {e}")
        send_text(sender, f"Failed to resolve conflict: {e}")


def notify_conflict(sender: str, conflict_id: str):
    """Send a proactive conflict notification to a user."""
    show_conflict(sender, conflict_id, user={"name": "System"})


def _format_ts(ts) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "Unknown time"
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = ts
        return dt.strftime("%H:%M, %d %b %Y")
    except Exception:
        return str(ts)
