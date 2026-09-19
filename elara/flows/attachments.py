from __future__ import annotations
import uuid
import logging
from whatsapp.ux import send_text, send_interactive_buttons
from elara.db import get_task_by_id, add_attachment, get_attachments, add_comment
from elara.session import set_elara_session, clear_elara_session

logger = logging.getLogger(__name__)


def prompt_attachment(to: str, task_id: str, user: dict):
    """Prompt user to send an image or PDF attachment for an Elara Home task."""
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    task_title = task.get("title", "Task")
    set_elara_session(to, "attach_awaiting", draft={"task_id": task_id})

    return send_text(
        to,
        f"📎 *Attach File — {task_id}*\n\n"
        f"Send an image or document (PDF) in this chat.\n"
        f"It will be linked to task *{task_title}*.\n\n"
        f"_Type *cancel* to go back._"
    )


def handle_attachment_upload(sender: str, task_id: str, media_data: dict, user: dict):
    """
    Handle an uploaded image/PDF attachment for an Elara Home task.
    1. Stores in elara_attachments table.
    2. Syncs into elara_tasks.attachments JSONB column.
    3. Adds an activity comment in elara_comments and elara_tasks.comments.
    4. Notifies Kanav if the task was created by him.
    """
    task = get_task_by_id(task_id)
    if not task:
        clear_elara_session(sender)
        return send_text(sender, f"❌ Task `{task_id}` not found.")

    try:
        media_id = media_data.get("id")
        mime_type = media_data.get("mime_type", "image/jpeg")
        custom_name = media_data.get("filename")

        if not media_id and not media_data.get("url"):
            send_text(sender, "Could not process the attachment. Please try again.")
            return

        file_ext = "jpg"
        if "pdf" in mime_type:
            file_ext = "pdf"
        elif "png" in mime_type:
            file_ext = "png"
        elif "jpeg" in mime_type or "jpg" in mime_type:
            file_ext = "jpg"
        elif custom_name and "." in custom_name:
            file_ext = custom_name.rsplit(".", 1)[1].lower()

        file_name = custom_name or f"{task_id}_{uuid.uuid4().hex[:6]}.{file_ext}"
        file_url = media_data.get("url") or f"whatsapp_media://{media_id}"

        user_name = user.get("name") or "Team Member"
        user_role = user.get("role") or "Member"

        # 1. Insert into elara_attachments & sync into elara_tasks.attachments
        add_attachment(
            task_id=task_id,
            file_url=file_url,
            file_name=file_name,
            file_type=mime_type,
            uploaded_by=user_name,
        )

        # 2. Record provenance/audit comment in elara_comments and elara_tasks.comments
        try:
            add_comment(
                task_id=task_id,
                user_name=user_name,
                user_role=user_role,
                content=f"📎 Attachment added: {file_name}",
            )
        except Exception as c_err:
            logger.warning(f"Failed to record attachment comment: {c_err}")

        # 3. Notify Kanav if this task was created by him
        try:
            from notifications.kanav_notifier import is_elara_task_created_by_kanav, notify_kanav_task_change
            if is_elara_task_created_by_kanav(task):
                notify_kanav_task_change(
                    task_id=task_id,
                    task_title=task.get("title", "Task"),
                    change_made=f"Attachment added: {file_name}",
                    changed_by=user_name,
                    domain="Elara Home",
                )
        except Exception as notif_err:
            logger.error(f"Failed to notify Kanav for Elara attachment: {notif_err}")

        # 4. Notify Rachit of Elara Home task change
        try:
            from notifications.rachit_notifier import notify_rachit_task_change
            notify_rachit_task_change(
                task_id=task_id,
                task_title=(task.get("title") if task else "Task") or "Task",
                change_made=f"Attachment added: {file_name}",
                changed_by=user_name,
                domain="Elara Home",
            )
        except Exception as notif_err:
            logger.error(f"Failed to notify Rachit for Elara attachment: {notif_err}")

        clear_elara_session(sender)

        buttons = [
            {"id": f"elara_view_{task_id}", "title": "View Task Card"},
            {"id": f"elara_viewatt_{task_id}", "title": "View Attachments"},
        ]

        task_title = task.get("title", "Task")
        return send_interactive_buttons(
            sender,
            f"📎 *Attachment Saved*\n\n"
            f"File linked to *'{task_title}'* successfully.\n\n"
            f"📄 *File:* `{file_name}`\n"
            f"👤 *Uploaded by:* {user_name}\n"
            f"*Elara Kanban:* ✅ Stored & Synced",
            buttons,
        )

    except Exception as e:
        logger.error(f"Elara attachment upload failed for {task_id}: {e}", exc_info=True)
        clear_elara_session(sender)
        return send_text(sender, "Failed to save attachment. Please try again.")


def show_task_attachments(to: str, task_id: str, user: dict):
    """Retrieve and display all attachments for an Elara Home task."""
    task = get_task_by_id(task_id)
    if not task:
        return send_text(to, f"❌ Task `{task_id}` not found.")

    attachments = get_attachments(task_id)
    task_title = task.get("title", "Task")

    if not attachments:
        buttons = [
            {"id": f"elara_attach_{task_id}", "title": "📎 Add Attachment"},
            {"id": f"elara_view_{task_id}", "title": "Back to Task"},
        ]
        return send_interactive_buttons(
            to,
            f"📎 *Attachments for '{task_title}'*\n\n"
            f"No attachments uploaded yet for this task.",
            buttons,
        )

    lines = [f"📎 *Attachments for '{task_title}'* ({len(attachments)} total):\n"]
    for i, att in enumerate(attachments, 1):
        fname = att.get("file_name", "File")
        uploader = att.get("uploaded_by", "User")
        uploaded_at = str(att.get("uploaded_at", "")).split("T")[0]
        lines.append(f"{i}. *{fname}*\n   👤 {uploader} | 📅 {uploaded_at}")

    lines.append("\n_Use the buttons below to add more or return._")
    body = "\n".join(lines)

    buttons = [
        {"id": f"elara_attach_{task_id}", "title": "📎 Add Another"},
        {"id": f"elara_view_{task_id}", "title": "Back to Task"},
    ]

    return send_interactive_buttons(to, body, buttons)
