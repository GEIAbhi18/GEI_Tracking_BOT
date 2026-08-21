"""
Screen — Completed Tasks Flow
===============================
Shows completed/closed tasks, option to filter by building or all buildings.
Fetches live changes from Google Sheets first to guarantee fresh data.
"""

import logging

from whatsapp.ux import send_text, send_list_message
from facilities.auth import get_permitted_buildings, assert_building_access
from facilities.sheets_client import list_rows_by_building
from facilities.flows.router import set_session, clear_session

logger = logging.getLogger(__name__)


def prompt_completed_tasks_building(sender: str, user: dict):
    """Ask which building to view completed tasks for."""
    from facilities.sync_engine import poll_sheet_changes
    try:
        poll_sheet_changes()  # Live sync from Google Sheets
    except Exception as e:
        logger.warning(f"Live poll before completed tasks failed: {e}")

    buildings = get_permitted_buildings(user)
    set_session(sender, "completed_tasks_building")

    rows = [{"id": "fac_completed_bldg_all", "title": "🌐 All Buildings", "description": "Completed tasks across all sites"}]
    for b in buildings:
        rows.append({"id": f"fac_completed_bldg_{b}", "title": f"🏗️ {b}", "description": f"Completed tasks in {b}"})

    sections = [{"title": "Select Building", "rows": rows[:10]}]
    send_list_message(
        sender,
        "🟢 *Completed Tasks — Select Building*\n\n"
        "Choose a building or select *All Buildings* to view completed tasks:",
        "Select Building",
        sections,
    )


def show_completed_tasks(sender: str, user: dict, building: str):
    """Show completed tasks for a specific building or all buildings."""
    from facilities.sync_engine import poll_sheet_changes
    try:
        poll_sheet_changes()  # Live sync from Google Sheets
    except Exception as e:
        logger.warning(f"Live poll before completed tasks failed: {e}")

    clear_session(sender)
    permitted = get_permitted_buildings(user)

    if building != "all":
        try:
            assert_building_access(user, building)
        except PermissionError as e:
            send_text(sender, f"🚫 {str(e)}")
            return
        target_buildings = [building]
    else:
        target_buildings = permitted

    all_tasks = []
    for bldg in target_buildings:
        all_tasks.extend(list_rows_by_building(bldg))

    # Filter for closed / completed tasks
    completed = [
        t for t in all_tasks
        if str(t.get("status", "")).strip().lower() in ("closed", "completed", "done")
    ]

    bldg_label = building if building != "all" else "All Permitted Buildings"

    if not completed:
        send_text(
            sender,
            f"🟢 *Completed Tasks — {bldg_label}*\n\n"
            f"No tasks have been marked as completed yet for {bldg_label}.\n\n"
            f"_Type *menu* to go back._"
        )
        return

    msg_parts = [
        f"🟢 *Completed Tasks — {bldg_label}*\n",
        f"Total Completed: *{len(completed)}*\n"
    ]

    list_rows = []
    for task in completed[:10]:
        ref = task.get("ref_no", "—")
        issue = task.get("issue_action", "No description")
        owner = task.get("owner", "Unassigned")
        b = task.get("building", "")
        ttype = task.get("type", "General")

        msg_parts.append(f"🟢 *{ref}* [{b}] — {issue[:40]}")
        msg_parts.append(f"   👤 {owner} | 📁 {ttype}\n")

        row_title = f"{ref} (Closed)"
        if len(row_title) > 24:
            row_title = row_title[:24]

        list_rows.append({
            "id": f"fac_view_{ref}",
            "title": row_title,
            "description": f"{owner}: {issue[:50]}" if issue else "",
        })

    if len(completed) > 10:
        msg_parts.append(f"\n_Showing 10 of {len(completed)} completed tasks._")

    message = "\n".join(msg_parts)

    if list_rows:
        sections = [{"title": "Tap to view details", "rows": list_rows}]
        send_list_message(sender, message, "View Tasks", sections)
    else:
        send_text(sender, message)
