from __future__ import annotations
import logging
from whatsapp.ux import send_text, send_interactive_buttons
from elara.db import get_task_by_id, add_comment, get_comments
from elara.session import set_elara_session, clear_elara_session

logger = logging.getLogger(__name__)


def prompt_add_comment(to: str, task_id: str, user: dict):
    """Prompt user to type a comment/note for a task."""
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    set_elara_session(to, "task_waiting_for_comment", draft={"task_id": task_id})
    return send_text(
        to,
        f"💬 *Add Comment to '{task.get('title')}'*\n\n"
        f"Please reply with your comment, update, or remark:\n"
        f"_(Type your message below)_"
    )


def handle_comment_text_input(to: str, text: str, user: dict, session: dict):
    """Save the incoming comment to elara_comments and sync with task."""
    draft = session.get("draft", {})
    task_id = draft.get("task_id")
    if not task_id:
        clear_elara_session(to)
        return send_text(to, "❌ Comment session expired. Please try again.")

    content = text.strip()
    if not content:
        return send_text(to, "Please enter a non-empty comment:")

    user_name = user.get("name", "User")
    user_role = user.get("role", "Team Member")

    # Add comment into elara_comments table & sync into elara_tasks
    created = add_comment(
        task_id=task_id,
        user_name=user_name,
        user_role=user_role,
        content=content,
    )
    clear_elara_session(to)

    buttons = [
        {"id": f"elara_viewcmts_{task_id}", "title": "View All Comments"},
        {"id": f"elara_view_{task_id}", "title": "View Task Card"},
    ]

    return send_interactive_buttons(
        to,
        f"✅ *Comment added successfully!*\n\n"
        f"💬 *{user_name}:* \"{content}\"",
        buttons,
    )


def show_task_comments(to: str, task_id: str, user: dict):
    """
    Retrieve and display all comments for a task from `elara_comments`.
    Guarantees full historical audit trail without overwriting.
    """
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    # Query all comments for this task from elara_comments
    comments = get_comments(task_id)

    if not comments:
        buttons = [
            {"id": f"elara_cmt_{task_id}", "title": "Add First Comment"},
            {"id": f"elara_view_{task_id}", "title": "Back to Task"},
        ]
        return send_interactive_buttons(
            to,
            f"💬 *Comments for '{task.get('title')}'*\n\n"
            f"No comments yet on this task.",
            buttons,
        )

    msg = f"💬 *Comments & History ({len(comments)})*\n"
    msg += f"Task: *{task.get('title')}*\n\n"

    for idx, c in enumerate(comments, 1):
        uname = c.get("user_name", "User")
        urole = c.get("user_role")
        role_tag = f" ({urole})" if urole else ""
        cdate = str(c.get("created_at", ""))
        if "T" in cdate:
            cdate = cdate.split("T")[0] + " " + cdate.split("T")[1][:5]
        content = c.get("content", "").strip()

        msg += f"*{idx}. {uname}*{role_tag} — _{cdate}_\n"
        msg += f"   \"{content}\"\n\n"

    buttons = [
        {"id": f"elara_cmt_{task_id}", "title": "Add New Comment"},
        {"id": f"elara_view_{task_id}", "title": "Back to Task"},
    ]

    return send_interactive_buttons(to, msg.strip(), buttons)
