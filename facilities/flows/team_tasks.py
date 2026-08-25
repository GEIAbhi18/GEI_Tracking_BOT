"""
Screen 03 — Team Tasks
========================
Shows all tasks for a specific building, scoped to user's permissions.
"""

import logging

from whatsapp.ux import send_text, send_list_message
from facilities.auth import assert_building_access
from facilities.sheets_client import list_rows_by_building
from facilities.config import RAG_STATUS_MAP

logger = logging.getLogger(__name__)


def show_team_tasks(sender: str, building: str, user: dict):
    """Show all tasks for a building (Screen 03)."""
    # Live poll Google Sheet first
    from facilities.sync_engine import poll_sheet_changes
    try:
        poll_sheet_changes()
    except Exception as e:
        logger.warning(f"Live poll in show_team_tasks failed: {e}")

    # Enforce permission
    try:
        assert_building_access(user, building)
    except PermissionError as e:
        send_text(sender, f"🚫 {str(e)}")
        return

    tasks = list_rows_by_building(building)

    if not tasks:
        send_text(
            sender,
            f"👥 *Team Tasks — {building}*\n\n"
            f"No tasks found for {building}.\n\n"
            f"_Type *menu* to go back._"
        )
        return

    # Sort by status priority: Open > WIP > Escalated > On Hold > Closed
    status_order = {"Open": 0, "Escalated": 1, "WIP": 2, "On Hold": 3, "Closed": 4}
    tasks.sort(key=lambda t: status_order.get(t.get("status", "Open"), 5))

    msg_parts = [f"👥 *Team Tasks — {building}*\n"]

    open_count = sum(1 for t in tasks if t.get("status") == "Open")
    wip_count = sum(1 for t in tasks if t.get("status") == "WIP")
    closed_count = sum(1 for t in tasks if t.get("status") == "Closed")

    msg_parts.append(
        f"🔴 Open: {open_count} | 🟡 WIP: {wip_count} | 🟢 Closed: {closed_count}\n"
    )

    from facilities.task_filter import enrich_task_with_responsible

    list_rows = []
    for task in tasks[:10]:  # Max 10 for List Message
        enrich_task_with_responsible(task)
        status = task.get("status", "Open")
        rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})
        ref = task.get("ref_no", "—")
        issue = task.get("issue_action", "No description")
        owner = task.get("owner", "Unassigned")
        responsible = task.get("responsible_user")

        owner_display = owner
        if responsible and responsible.lower() != owner.lower():
            owner_display = f"{owner} ({responsible})"

        msg_parts.append(f"{rag['emoji']} *{ref}* — {issue[:40]}")
        msg_parts.append(f"   👤 {owner_display} | 📅 {task.get('target_date', '—')}\n")

        row_title = f"{ref} ({rag['label']})"
        if len(row_title) > 24:
            row_title = row_title[:24]
        list_rows.append({
            "id": f"fac_view_{ref}",
            "title": row_title,
            "description": f"{owner_display}: {issue[:50]}" if issue else "",
        })

    if len(tasks) > 10:
        msg_parts.append(f"\n_Showing 10 of {len(tasks)} tasks._")

    message = "\n".join(msg_parts)

    if list_rows:
        sections = [{"title": f"{building} Tasks", "rows": list_rows}]
        send_list_message(sender, message, "View Tasks", sections)
    else:
        send_text(sender, message)
