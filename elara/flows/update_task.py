from __future__ import annotations
import logging
from typing import Any
from whatsapp.ux import send_interactive_buttons, send_list_message, send_text
from elara.db import get_task_by_id, update_task
from elara.session import set_elara_session, clear_elara_session, get_elara_session
from elara.config import STATUS_DISPLAY_NAMES, VALID_STATUSES
from elara.flows.task_card import send_elara_task_card

logger = logging.getLogger(__name__)


def start_update_task_flow(to: str, task_id: str, user: dict):
    """Present status change options for a task."""
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found in Elara Home.")

    title = task.get("title", "Task")
    current_status = STATUS_DISPLAY_NAMES.get(task.get("status", "pending"), "Pending")

    buttons = [
        {"id": f"elara_setst_{task_id}_in_progress", "title": "In Progress"},
        {"id": f"elara_setst_{task_id}_completed", "title": "Completed"},
        {"id": f"elara_morest_{task_id}", "title": "More Statuses..."},
    ]

    return send_interactive_buttons(
        to,
        f"🔄 *Update Status: {title}*\n"
        f"Current Status: *{current_status}*\n\n"
        f"Select new status:",
        buttons,
    )


def show_all_statuses(to: str, task_id: str, user: dict):
    """Show list of all 5 available statuses."""
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    rows = []
    for st in VALID_STATUSES:
        rows.append({
            "id": f"elara_setst_{task_id}_{st}",
            "title": STATUS_DISPLAY_NAMES[st][:24],
            "description": f"Set status to {STATUS_DISPLAY_NAMES[st]}"[:72],
        })

    sections = [{"title": "Select New Status", "rows": rows}]
    return send_list_message(
        to,
        f"Select status for *{task.get('title', 'Task')}*:",
        "Select Status",
        sections,
    )


def handle_status_selection(to: str, task_id: str, new_status: str, user: dict):
    """Apply new status to the task in elara_tasks table."""
    norm_status = new_status.lower()
    if norm_status not in VALID_STATUSES:
        norm_status = "pending"

    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    if norm_status == "blocker":
        # Ask for blocker reason
        set_elara_session(to, "update_task_blocker_reason", draft={"task_id": task_id, "status": "blocker"})
        return send_text(
            to,
            f"🛑 Marking *{task.get('title')}* as *Blocker*.\n\n"
            f"Please enter the *Blocker Reason*:"
        )

    # Apply update to elara_tasks
    updates: dict[str, Any] = {"status": norm_status}
    if norm_status == "in_progress" and (task.get("progress") or 0) == 0:
        updates["progress"] = 25

    updated = update_task(task_id, updates)
    status_str = STATUS_DISPLAY_NAMES.get(norm_status, norm_status)
    old_status = task.get("status", "pending")
    old_status_str = STATUS_DISPLAY_NAMES.get(old_status, old_status)

    # ── Notify Kanav if this task was created by him ──
    try:
        from notifications.kanav_notifier import is_elara_task_created_by_kanav, notify_kanav_task_change
        if is_elara_task_created_by_kanav(task):
            actor_name = user.get("name", "Team Member")
            if norm_status == "completed":
                change_desc = f"Status changed from {old_status_str} to Completed (Task closed)"
            else:
                change_desc = f"Status changed from {old_status_str} to {status_str}"
            notify_kanav_task_change(
                task_id=task_id,
                task_title=task.get("title", "Task"),
                change_made=change_desc,
                changed_by=actor_name,
                domain="Elara Home"
            )
    except Exception as notif_err:
        logger.error(f"Failed to notify Kanav in handle_status_selection: {notif_err}")

    send_text(to, f"✅ Task status updated to *{status_str}*!")
    if updated:
        send_elara_task_card(to, updated)

    # Prompt if user wants to add an update note / comment
    buttons = [
        {"id": f"elara_cmt_{task_id}", "title": "Add Comment/Note"},
        {"id": "elara_home", "title": "Elara Home Menu"},
    ]
    return send_interactive_buttons(
        to,
        f"Would you like to add a comment or update note to *{task.get('title')}*?",
        buttons,
    )


def handle_blocker_reason_input(to: str, text: str, user: dict, session: dict):
    """Save blocker reason and mark task as blocker."""
    draft = session.get("draft", {})
    task_id = draft.get("task_id")
    if not task_id:
        clear_elara_session(to)
        return send_text(to, "❌ Task session expired. Please try again.")

    reason = text.strip()
    updates = {
        "status": "blocker",
        "is_blocked": True,
        "blocker_reason": reason,
    }
    updated = update_task(task_id, updates)
    clear_elara_session(to)

    # Also automatically record as a comment
    from elara.db import add_comment
    add_comment(
        task_id=task_id,
        user_name=user.get("name", "User"),
        user_role=user.get("role", "Team Member"),
        content=f"🛑 Marked as Blocker: {reason}",
    )

    # ── Notify Kanav if this task was created by him ──
    try:
        from notifications.kanav_notifier import is_elara_task_created_by_kanav, notify_kanav_task_change
        task = get_task_by_id(task_id)
        if task and is_elara_task_created_by_kanav(task):
            actor_name = user.get("name", "Team Member")
            notify_kanav_task_change(
                task_id=task_id,
                task_title=task.get("title", "Task"),
                change_made=f"Status changed to Blocker (Reason: {reason})",
                changed_by=actor_name,
                domain="Elara Home"
            )
    except Exception as notif_err:
        logger.error(f"Failed to notify Kanav in handle_blocker_reason_input: {notif_err}")

    send_text(to, f"🛑 Task marked as *Blocker*!\nReason: _{reason}_")
    if updated:
        return send_elara_task_card(to, updated)
