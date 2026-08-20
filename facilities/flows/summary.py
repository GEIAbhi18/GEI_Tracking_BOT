"""
Screen 11 — Summary
=====================
Live rollup query: Active/Open/WIP/Closed overall + per-building.
Computed at request time, not cached.
"""

import logging
from collections import defaultdict

from whatsapp.ux import send_text
from facilities.auth import get_permitted_buildings
from facilities.sheets_client import list_rows_by_building
from facilities.config import RAG_STATUS_MAP

logger = logging.getLogger(__name__)


def show_summary(sender: str, user: dict):
    """Show the live summary rollup (Screen 11)."""
    buildings = get_permitted_buildings(user)

    overall = defaultdict(int)
    per_building = {}
    total = 0

    for building in buildings:
        tasks = list_rows_by_building(building)
        counts = defaultdict(int)

        for task in tasks:
            status = task.get("status", "Open")
            counts[status] += 1
            overall[status] += 1
            total += 1

        per_building[building] = dict(counts)

    if total == 0:
        send_text(
            sender,
            "📊 *Facilities Summary*\n\n"
            "No tasks found across your buildings.\n\n"
            "_Type *menu* to go back._"
        )
        return

    msg_parts = [
        "📊 *Facilities Summary*\n",
        f"*Total Tasks:* {total}\n",
    ]

    # Overall counts
    for status in ["Open", "WIP", "Closed", "On Hold", "Escalated"]:
        count = overall.get(status, 0)
        if count > 0:
            rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪"})
            msg_parts.append(f"  {rag['emoji']} {status}: {count}")

    msg_parts.append("")

    # Per-building breakdown
    for building in buildings:
        if building not in per_building or not per_building[building]:
            continue

        counts = per_building[building]
        bldg_total = sum(counts.values())
        msg_parts.append(f"🏗️ *{building}* ({bldg_total} tasks)")

        for status in ["Open", "WIP", "Closed", "On Hold", "Escalated"]:
            count = counts.get(status, 0)
            if count > 0:
                rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪"})
                msg_parts.append(f"  {rag['emoji']} {status}: {count}")

        msg_parts.append("")

    msg_parts.append("_Computed live — not cached._")

    send_text(sender, "\n".join(msg_parts))
