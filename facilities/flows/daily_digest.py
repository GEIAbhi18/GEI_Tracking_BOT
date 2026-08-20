"""
Screen 20 — Daily Activity Digest
====================================
End-to-end daily activity across GEI_BOT + Sheet events
for the requesting user's permitted buildings.
"""

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from whatsapp.ux import send_text
from db import supabase
from facilities.auth import get_permitted_buildings

logger = logging.getLogger(__name__)


def show_daily_digest(sender: str, user: dict):
    """Show today's activity digest (Screen 20)."""
    buildings = get_permitted_buildings(user)

    # Get today's date range (UTC)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        # Get all audit entries for today across user's buildings
        result = supabase.table("facilities_audit_log").select("*").gte(
            "timestamp", today_start.isoformat()
        ).order("timestamp", desc=False).execute()

        entries = result.data or []

        # Filter to only user's permitted buildings
        filtered = []
        for entry in entries:
            ref_no = entry.get("ref_no", "")
            # Check if this ref_no belongs to a permitted building
            for building in buildings:
                if ref_no.startswith(building):
                    filtered.append(entry)
                    break

        if not filtered:
            send_text(
                sender,
                f"📝 *Daily Digest — {now.strftime('%d %b %Y')}*\n\n"
                f"No activity recorded today across your buildings.\n\n"
                f"_Type *menu* to go back._"
            )
            return

        # Group by source
        bot_events = [e for e in filtered if e.get("source") == "gei_bot"]
        sheet_events = [e for e in filtered if e.get("source") == "google_sheets"]
        system_events = [e for e in filtered if e.get("source") == "system"]

        # Group by building
        by_building = defaultdict(list)
        for entry in filtered:
            ref_no = entry.get("ref_no", "")
            for building in buildings:
                if ref_no.startswith(building):
                    by_building[building].append(entry)
                    break

        msg_parts = [
            f"📝 *Daily Digest — {now.strftime('%d %b %Y')}*\n",
            f"📊 *{len(filtered)} events* across {len(by_building)} building(s)\n",
            f"  📱 GEI_BOT: {len(bot_events)} events",
            f"  📊 Google Sheets: {len(sheet_events)} events",
        ]

        if system_events:
            msg_parts.append(f"  ⚙️ System: {len(system_events)} events")

        # Per-building breakdown
        for building in buildings:
            if building not in by_building:
                continue

            events = by_building[building]
            msg_parts.append(f"\n🏗️ *{building}* ({len(events)} events)")

            # Show last 5 events per building
            for event in events[-5:]:
                source_icon = "📱" if event["source"] == "gei_bot" else "📊"
                ts = _format_time(event.get("timestamp"))
                actor = event.get("actor", "—")
                action = event.get("action", "—")
                ref = event.get("ref_no", "—")

                msg_parts.append(
                    f"  {source_icon} {ts} — {ref}: {action[:40]}"
                    f" _{actor}_"
                )

            if len(events) > 5:
                msg_parts.append(f"  _...and {len(events) - 5} more_")

        message = "\n".join(msg_parts)

        if len(message) > 4000:
            message = message[:3950] + "\n\n_...digest truncated._"

        send_text(sender, message)

    except Exception as e:
        logger.error(f"show_daily_digest failed: {e}", exc_info=True)
        send_text(sender, "Failed to generate daily digest. Please try again.")


def _format_time(ts) -> str:
    """Format a timestamp to just time."""
    if not ts:
        return "—"
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = ts
        return dt.strftime("%H:%M")
    except Exception:
        return "—"
