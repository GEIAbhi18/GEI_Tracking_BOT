"""
Screen 19 — History
=====================
Pull full audit_log for a Ref No.
Both GEI_BOT-side and Sheet-side entries, chronological.
"""

import logging
from datetime import datetime

from whatsapp.ux import send_text
from db import supabase

logger = logging.getLogger(__name__)


def show_history(sender: str, ref_no: str, user: dict):
    """Show full audit history for a Ref No (Screen 19)."""
    try:
        result = supabase.table("facilities_audit_log").select("*").eq(
            "ref_no", ref_no
        ).order("timestamp", desc=False).execute()

        entries = result.data or []

        if not entries:
            send_text(
                sender,
                f"📜 *History — {ref_no}*\n\n"
                f"No history entries found for this task."
            )
            return

        msg_parts = [f"📜 *History — {ref_no}*\n"]

        for entry in entries:
            source = entry.get("source", "system")
            source_icon = _source_icon(source)
            actor = entry.get("actor", "—")
            action = entry.get("action", "—")
            field = entry.get("field")
            old_val = entry.get("old_value")
            new_val = entry.get("new_value")
            ts = _format_timestamp(entry.get("timestamp"))

            msg_parts.append(f"\n{source_icon} *{action}*")
            msg_parts.append(f"  👤 {actor} | 🕐 {ts}")

            if field and old_val and new_val:
                msg_parts.append(f"  {field}: \"{old_val}\" → \"{new_val}\"")
            elif field and new_val:
                msg_parts.append(f"  {field}: → \"{new_val}\"")

        # Add attachments
        try:
            attach_res = supabase.table("facilities_attachments").select("*").eq(
                "ref_no", ref_no
            ).order("uploaded_at").execute()

            if attach_res.data:
                msg_parts.append(f"\n📎 *Attachments ({len(attach_res.data)})*")
                for att in attach_res.data:
                    att_ts = _format_timestamp(att.get("uploaded_at"))
                    msg_parts.append(
                        f"  📄 {att.get('file_name', 'file')} — "
                        f"by {att.get('uploaded_by', '—')} at {att_ts}"
                    )
        except Exception:
            pass

        message = "\n".join(msg_parts)

        # WhatsApp has a ~4096 char limit
        if len(message) > 4000:
            message = message[:3950] + "\n\n_...history truncated. Contact admin for full log._"

        send_text(sender, message)

    except Exception as e:
        logger.error(f"show_history failed for {ref_no}: {e}")
        send_text(sender, f"Failed to load history for {ref_no}.")


def _source_icon(source: str) -> str:
    """Get an icon for the audit source."""
    icons = {
        "gei_bot": "📱",
        "google_sheets": "📊",
        "system": "⚙️",
    }
    return icons.get(source, "📝")


def _format_timestamp(ts) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "—"
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = ts
        return dt.strftime("%d %b, %H:%M")
    except Exception:
        return str(ts)[:16]
