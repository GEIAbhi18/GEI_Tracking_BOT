"""
Screen 02 — My Tasks
=====================
Grouped by Building → Type → Task with RAG status chips.
Shows max 4 tasks per group with "View all N" when truncated.
"""

import logging
from collections import defaultdict

from whatsapp.ux import send_text, send_list_message
from facilities.auth import get_permitted_buildings
from facilities.sheets_client import list_rows_by_building
from facilities.config import RAG_STATUS_MAP

logger = logging.getLogger(__name__)


def show_my_tasks(sender: str, user: dict):
    """Show tasks assigned to the user (via Owner Position mapping), grouped by Building → Type."""
    from facilities.flows.router import clear_session
    clear_session(sender)

    # Live poll Google Sheet first
    from facilities.sync_engine import poll_sheet_changes
    from facilities.owner_resolver import get_position_titles_for_user
    from facilities.task_filter import enrich_task_with_responsible
    try:
        poll_sheet_changes()
    except Exception as e:
        logger.warning(f"Live poll in show_my_tasks failed: {e}")

    buildings = get_permitted_buildings(user)
    user_name = user.get("name", "")

    # Get user's owner position titles
    from facilities.owner_resolver import normalize_position_title
    user_positions = [p.lower() for p in get_position_titles_for_user(user_name)]
    norm_positions = [normalize_position_title(p) for p in user_positions]

    # Get all tasks across permitted buildings
    raw_tasks = []
    for building in buildings:
        raw_tasks.extend(list_rows_by_building(building))

    # Filter to user's tasks if user has mapped positions; otherwise show tasks matching their name directly
    tasks = []
    for task in raw_tasks:
        enrich_task_with_responsible(task)
        owner = (task.get("owner") or "").strip()
        owner_norm = normalize_position_title(owner)
        resp_user = (task.get("responsible_user") or "").strip()

        is_match = False
        if user_positions:
            if (
                owner.lower() in user_positions
                or owner_norm in norm_positions
                or (resp_user and resp_user.lower() == user_name.lower())
                or (user_name and owner.lower() == user_name.lower())
            ):
                is_match = True
        elif user_name:
            if (
                owner.lower() == user_name.lower()
                or (resp_user and resp_user.lower() == user_name.lower())
            ):
                is_match = True
        else:
            is_match = True

        if is_match:
            tasks.append(task)

    # If no specific tasks found and user is Director/Developer, fallback to showing all permitted
    if not tasks and user.get("role") in ("Director", "Developer"):
        tasks = raw_tasks
        for task in tasks:
            enrich_task_with_responsible(task)

    if not tasks:
        send_text(
            sender,
            f"📋 *My Tasks*\n\n"
            f"You have no tasks assigned to you across any building.\n\n"
            f"_Type *menu* to go back._"
        )
        return

    # Group by building → type
    grouped = defaultdict(lambda: defaultdict(list))
    for task in tasks:
        bldg = task.get("building", "Unknown")
        ttype = task.get("type", "General")
        grouped[bldg][ttype].append(task)

    # Build the message
    msg_parts = ["📋 *My Tasks*\n"]
    list_rows = []

    for building in buildings:
        if building not in grouped:
            continue

        msg_parts.append(f"\n🏗️ *{building}*")

        for task_type, type_tasks in sorted(grouped[building].items()):
            msg_parts.append(f"  📁 *{task_type}*")

            # Show max 4 tasks, with "View all N" if more
            shown = type_tasks[:4]
            for task in shown:
                status = task.get("status", "Open")
                rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})
                ref = task.get("ref_no", "—")
                issue = task.get("issue_action", "No description")
                if len(issue) > 50:
                    issue = issue[:47] + "..."

                msg_parts.append(f"    {rag['emoji']} {ref}: {issue}")

                # Add to list message rows for tap-to-view
                row_title = f"{ref} ({rag['label']})"
                if len(row_title) > 24:
                    row_title = row_title[:24]
                list_rows.append({
                    "id": f"fac_view_{ref}",
                    "title": row_title,
                    "description": issue[:72] if issue else "",
                })

            if len(type_tasks) > 4:
                remaining = len(type_tasks) - 4
                msg_parts.append(f"    _...and {remaining} more_")
                # Add "View all" row
                view_all_id = f"fac_viewall_{building}_{task_type}"
                if len(view_all_id) > 200:
                    view_all_id = view_all_id[:200]
                list_rows.append({
                    "id": view_all_id,
                    "title": f"View all {len(type_tasks)}",
                    "description": f"All {task_type} tasks in {building}",
                })

    total = len(tasks)
    open_count = sum(1 for t in tasks if t.get("status") == "Open")
    wip_count = sum(1 for t in tasks if t.get("status") == "WIP")
    closed_count = sum(1 for t in tasks if t.get("status") == "Closed")

    msg_parts.append(
        f"\n📊 *Total:* {total} | 🔴 Open: {open_count} | 🟡 WIP: {wip_count} | 🟢 Closed: {closed_count}"
    )

    message = "\n".join(msg_parts)

    if list_rows:
        # Limit to 10 rows (WhatsApp List Message max)
        if len(list_rows) > 10:
            list_rows = list_rows[:10]
        sections = [{"title": "Tap to view task", "rows": list_rows}]
        send_list_message(sender, message, "View Tasks", sections)
    else:
        send_text(sender, message)


def show_tasks_by_type(sender: str, user: dict, building: str, task_type: str):
    """Show all tasks for a specific building+type (expanded view)."""
    tasks = list_rows_by_building(building)

    filtered = [
        t for t in tasks
        if t.get("type") == task_type
    ]

    if not filtered:
        send_text(sender, f"No {task_type} tasks found in {building}.")
        return

    msg_parts = [f"📋 *All {task_type} Tasks — {building}*\n"]
    list_rows = []

    for task in filtered:
        status = task.get("status", "Open")
        rag = RAG_STATUS_MAP.get(status, {"emoji": "⚪", "label": status})
        ref = task.get("ref_no", "—")
        issue = task.get("issue_action", "No description")
        target = task.get("target_date", "—")

        msg_parts.append(f"{rag['emoji']} *{ref}*: {issue}")
        msg_parts.append(f"   📅 Target: {target} | Status: {status}\n")

        row_title = f"{ref} ({rag['label']})"
        if len(row_title) > 24:
            row_title = row_title[:24]
        list_rows.append({
            "id": f"fac_view_{ref}",
            "title": row_title,
            "description": issue[:72] if issue else "",
        })

    message = "\n".join(msg_parts)

    if list_rows and len(list_rows) <= 10:
        sections = [{"title": "Tap to view", "rows": list_rows}]
        send_list_message(sender, message, "View Tasks", sections)
    else:
        send_text(sender, message)
