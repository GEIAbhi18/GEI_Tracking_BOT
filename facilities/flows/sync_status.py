"""
Screen 12 — Sync Status Card
===============================
Connection, Two-way Sync, Last Successful Sync, Pending count,
Failed count, Integration Health — plain language, zero jargon.
"""

import logging
from datetime import datetime, timezone

from whatsapp.ux import send_text
from facilities.sheets_client import get_sync_status

logger = logging.getLogger(__name__)


def show_sync_status(sender: str, user: dict):
    """Show the sync status card (Screen 12)."""
    status = get_sync_status()

    # Format last sync time
    last_sync = status.get("last_successful_sync")
    if last_sync:
        try:
            if isinstance(last_sync, str):
                dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            else:
                dt = last_sync
            last_sync_str = dt.strftime("%H:%M, %d %b %Y")
        except Exception:
            last_sync_str = str(last_sync)
    else:
        last_sync_str = "Never"

    msg = (
        f"🔗 *Google Sheets Sync Status*\n"
        f"{'─' * 25}\n\n"
        f"📡 *Connection:* {status.get('connection', '—')}\n"
        f"🔄 *Two-way Sync:* {status.get('two_way_sync', '—')}\n"
        f"🕐 *Last Successful Sync:* {last_sync_str}\n"
        f"⏳ *Pending Updates:* {status.get('pending_count', 0)}\n"
        f"❌ *Failed Updates:* {status.get('failed_count', 0)}\n\n"
        f"🏥 *Integration Health:* {status.get('health', '—')}\n\n"
        f"_Changes you make here are automatically synced to the "
        f"Facilities Master Tracker sheet, and vice versa._"
    )

    send_text(sender, msg)
