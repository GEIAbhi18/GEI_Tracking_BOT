from __future__ import annotations
from whatsapp.ux import send_interactive_buttons, send_text
from elara.db import get_project_by_id, get_comments
from elara.config import STATUS_DISPLAY_NAMES


def format_progress_bar(progress: int) -> str:
    """Render a visual 10-block progress bar."""
    filled = max(0, min(10, round(progress / 10)))
    return "▓" * filled + "░" * (10 - filled)


def send_elara_task_card(to: str, task: dict):
    """
    Render a rich WhatsApp task card for an Elara Home task.
    Includes status, assignees, dates, and interactive action buttons.
    """
    task_id = task.get("id", "")
    title = task.get("title", "Untitled Task")
    status_raw = task.get("status", "pending")
    status_str = STATUS_DISPLAY_NAMES.get(status_raw, status_raw.capitalize())
    priority = (task.get("priority") or "medium").capitalize()
    progress = task.get("progress") or 0
    due_date = task.get("due_date") or "Not set"
    if "T" in str(due_date):
        due_date = str(due_date).split("T")[0]

    # Resolve project and department
    project_id = task.get("project_id", "")
    project = get_project_by_id(project_id) if project_id else None
    proj_name = project.get("name", "Elara Project") if project else "General Project"
    dept_name = project.get("department", "Elara Home") if project else "Elara Home"

    # Assignees
    assignees = task.get("assigned_users") or []
    assignee_str = ", ".join(assignees) if assignees else "Unassigned"

    # Status emoji
    status_emoji = {
        "pending": "⏳",
        "in_progress": "🔄",
        "delay": "⚠️",
        "blocker": "🛑",
        "completed": "✅",
    }.get(status_raw, "📌")

    # Comments count
    comments_list = task.get("comments") or []
    comments_count = len(comments_list) if isinstance(comments_list, list) else 0

    body = (
        f"📁 *{proj_name}* ({dept_name})\n"
        f"*{title}*\n\n"
        f"🆔 `ID: {task_id}`\n"
        f"{status_emoji} *Status:* {status_str}\n"
        f"🎯 *Priority:* {priority}\n"
        f"👤 *Assigned:* {assignee_str}\n"
        f"📅 *Due Date:* {due_date}\n"
        f"📊 *Progress:* {progress}% [{format_progress_bar(progress)}]\n"
        f"💬 *Comments:* {comments_count}\n"
    )

    if task.get("is_blocked") and task.get("blocker_reason"):
        body += f"\n🛑 *Blocker:* {task.get('blocker_reason')}\n"

    # Action buttons (max 3 buttons, <= 20 chars each)
    buttons = [
        {"id": f"elara_stat_{task_id}", "title": "Update Status"},
        {"id": f"elara_cmt_{task_id}", "title": "Add Comment"},
        {"id": f"elara_viewcmts_{task_id}", "title": "View Comments"},
    ]

    return send_interactive_buttons(to, body, buttons)
