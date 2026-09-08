from __future__ import annotations

"""
Facilities Module — Centralized Notifications
================================================
All Facilities task notifications go through this module.

Resolves Owner Position → User → WhatsApp number using the central
owner_resolver before sending any notification.

Never sends notifications to the wrong person. If a position has no
mapped user, logs the issue and skips the notification.
"""

import logging
from datetime import datetime, timezone

from db import supabase
from facilities.owner_resolver import (
    resolve_position_to_user,
    get_responsible_user_whatsapp,
)

logger = logging.getLogger(__name__)


def notify_task_owner(ref_no: str, event_type: str, context: dict) -> bool:
    """
    Send a notification to the owner of a task, resolved via position mapping.

    Flow:
        1. Look up the task's owner position from row_cache
        2. Resolve position → user via owner_resolver
        3. Look up user's WhatsApp number
        4. Send the notification

    Args:
        ref_no: Task reference number
        event_type: Type of event (e.g., "task_update_required", "external_change")
        context: Additional context for the notification message

    Returns:
        True if notification was sent, False otherwise
    """
    try:
        # 1. Get the task's owner position
        cache_res = supabase.table("row_cache").select(
            "owner, building, issue_action, target_date, status, type"
        ).eq("ref_no", ref_no).execute()

        if not cache_res.data:
            logger.warning(f"Cannot notify: task {ref_no} not found in cache")
            return False

        task = cache_res.data[0]
        owner_position = (task.get("owner") or "").strip()

        if not owner_position:
            logger.warning(f"Cannot notify: task {ref_no} has no owner")
            return False

        # 2. Resolve position → user + WhatsApp
        recipient = get_responsible_user_whatsapp(owner_position)

        if not recipient:
            logger.warning(
                f"Cannot notify: Owner Position '{owner_position}' for task {ref_no} "
                f"has no mapped user or no WhatsApp number. "
                f"Please add a mapping in facilities_owner_positions."
            )
            return False

        wa_number = recipient["whatsapp_number"]
        user_name = recipient["user_name"]

        # 3. Format the message
        msg = _format_notification(event_type, ref_no, task, context, user_name)

        # 4. Send via WhatsApp
        from whatsapp.ux import send_text
        send_text(wa_number, msg)
        logger.info(
            f"Notification sent to {user_name} ({wa_number}) for {ref_no} "
            f"[event={event_type}]"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to notify task owner for {ref_no}: {e}", exc_info=True)
        return False


def notify_user_by_position(position_title: str, message: str) -> bool:
    """
    Send a notification to a user identified by their position title.

    Args:
        position_title: Owner position from the Google Sheet
        message: The notification message to send

    Returns:
        True if sent, False otherwise
    """
    try:
        recipient = get_responsible_user_whatsapp(position_title)
        if not recipient:
            logger.warning(
                f"Cannot notify: position '{position_title}' has no mapped user "
                f"or user has no WhatsApp number."
            )
            return False

        from whatsapp.ux import send_text
        send_text(recipient["whatsapp_number"], message)
        logger.info(f"Notification sent to {recipient['user_name']} for position '{position_title}'")
        return True

    except Exception as e:
        logger.error(f"Failed to notify position '{position_title}': {e}")
        return False


def format_task_update_notification(task: dict, update_text: str = None) -> str:
    """
    Format the task update notification per spec Section 7.

    Returns the formatted WhatsApp message.
    """
    ref = task.get("ref_no", "—")
    issue = task.get("issue_action", "No description")
    building = task.get("building", "—")
    planned = task.get("planned_date") or task.get("target_date", "—") or "—"
    est_comp = task.get("estimated_completion_date", "—") or "—"
    status = task.get("status", "—")
    task_type = task.get("type", "—")

    msg = (
        f"🔔 *Task Update Required*\n\n"
        f"*Task:* {issue}\n"
        f"*Ref:* {ref}\n"
        f"*Building:* {building}\n"
        f"*Type:* {task_type}\n"
        f"*Planned Date:* {planned}\n"
        f"*Estimated Completion Date:* {est_comp}\n"
        f"*Status:* {status}\n"
    )

    if update_text:
        msg += f"\n*Update:* {update_text}\n"

    msg += (
        f"\nPlease update this task in GEI_BOT.\n\n"
        f"*How to update:*\n"
        f"Simply reply with the latest update.\n\n"
        f"_Example: Electrical work completed. Testing pending._\n\n"
        f"_Voice notes also work._"
    )

    return msg


def format_overdue_notification(task: dict) -> str:
    """
    Format an overdue task notification.

    Returns the formatted WhatsApp message.
    """
    from facilities.task_filter import calculate_delay_days

    ref = task.get("ref_no", "—")
    issue = task.get("issue_action", "No description")
    building = task.get("building", "—")
    planned = task.get("planned_date") or task.get("target_date", "—") or "—"
    est_comp = task.get("estimated_completion_date", "—") or "—"
    status = task.get("status", "—")
    delay = calculate_delay_days(task)

    return (
        f"⚠️ *Overdue Task Alert*\n\n"
        f"*Task:* {issue}\n"
        f"*Ref:* {ref}\n"
        f"*Building:* {building}\n"
        f"*Planned Date:* {planned}\n"
        f"*Estimated Completion Date:* {est_comp}\n"
        f"*Status:* {status}\n"
        f"*Delay:* {delay} day{'s' if delay != 1 else ''}\n\n"
        f"Please update this task or provide a revised timeline.\n\n"
        f"_Reply with an update to proceed._"
    )


def format_task_update_confirmation(task: dict, update_text: str,
                                      new_status: str = None) -> str:
    """
    Format the task update confirmation per spec Section 8.

    Returns the formatted WhatsApp message.
    """
    ref = task.get("ref_no", "—")
    issue = task.get("issue_action", "No description")
    status = new_status or task.get("status", "—")

    return (
        f"✅ *Task updated successfully*\n\n"
        f"*Task:* {issue}\n"
        f"*Ref:* {ref}\n"
        f"*Update:* {update_text}\n"
        f"*Status:* {status}"
    )


# ── Internal Helpers ─────────────────────────────────────────────────────────

def _format_notification(event_type: str, ref_no: str, task: dict,
                           context: dict, user_name: str) -> str:
    """Format a notification message based on event type."""

    if event_type == "task_update_required":
        return format_task_update_notification(task)

    elif event_type == "overdue":
        return format_overdue_notification(task)

    elif event_type == "external_change":
        field = context.get("field", "unknown field")
        old_val = context.get("old_value", "—")
        new_val = context.get("new_value", "—")
        now = datetime.now(timezone.utc).strftime("%H:%M UTC, %d %b %Y")

        return (
            f"📊 *Detected from Google Sheets*\n\n"
            f"*Ref:* {ref_no}\n"
            f"*Field:* {field}\n"
            f"*Previous:* {old_val}\n"
            f"*Updated to:* {new_val}\n\n"
            f"🕐 Detected at {now}\n\n"
            f"_This change was made directly on the Google Sheet._"
        )

    elif event_type == "created_externally":
        now = datetime.now(timezone.utc).strftime("%H:%M UTC, %d %b %Y")
        return (
            f"📊 *Detected from Google Sheets*\n\n"
            f"*New Task:* {ref_no}\n"
            f"A new task was created directly on the Google Sheet.\n\n"
            f"🕐 Detected at {now}"
        )

    elif event_type == "sync_success":
        field = context.get("field", "unknown")
        value = context.get("value", "—")
        return (
            f"✅ *Sync Update — {ref_no}*\n\n"
            f"*Google Sheets:* ✅ Synced\n"
            f"The {field} update to *\"{value}\"* has been successfully "
            f"synced to Google Sheets after a previous failure.\n\n"
            f"_No action needed._"
        )

    else:
        return (
            f"🔔 *Task Notification*\n\n"
            f"*Ref:* {ref_no}\n"
            f"*Event:* {event_type}\n"
            f"{context.get('message', '')}"
        )
